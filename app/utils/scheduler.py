import hashlib
import re
import uuid

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import desc, select

log = structlog.get_logger()
_scheduler: AsyncIOScheduler | None = None

_QUERY_NORMALIZE_RE = re.compile(r"\s+")
_SYNONYM_FUZZY_CACHE_TTL_S = 86400


def _match_cache_key(query: str) -> str:
    norm = _QUERY_NORMALIZE_RE.sub(" ", (query or "").strip()).upper()
    return "match:v1:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()


async def seed_synonym_fuzzy_cache_job():
    from app.models.database import HsnCode, Prediction, async_session
    from app.services.hsn_master import canonicalize_hsn
    from app.services.normalizer import normalize_product_name
    from app.utils.cache import set_cache

    seen: set[str] = set()
    warmed = 0
    try:
        async with async_session() as session:
            stmt = (
                select(Prediction)
                .where(
                    Prediction.source.in_([
                        "product_trigram",
                        "product_ilike",
                        "product_rapidfuzz",
                        "synonym_fuzzy_match",
                        "faiss_token",
                        "trigram_high",
                    ]),
                    Prediction.confidence >= 65,
                )
                .order_by(desc(Prediction.id))
                .limit(5000)
            )
            rows = (await session.execute(stmt)).scalars().all()

            for row in rows:
                if row.input_text in seen:
                    continue
                seen.add(row.input_text)

                code = canonicalize_hsn(row.predicted_hsn) or row.predicted_hsn
                desc_text = ""
                gst = None
                try:
                    hres = await session.execute(select(HsnCode).where(HsnCode.hsn_code == code).limit(1))
                    hc = hres.scalar_one_or_none()
                    if hc:
                        desc_text = (hc.description or "").strip()
                        if hc.gst_rate is not None:
                            gst = float(hc.gst_rate)
                except Exception:
                    pass

                if not desc_text:
                    desc_text = f"HSN {code}"

                score = float(row.confidence)
                label = "high" if score >= 0.80 else ("medium" if score >= 0.55 else "low")
                ch = code[:2] if len(code) >= 2 else None

                payload = {
                    "request_id": str(uuid.uuid4()),
                    "input_text": row.input_text,
                    "top_match": {
                        "hsn_code": code,
                        "description": desc_text,
                        "full_description": None,
                        "score": score,
                        "method": "synonym_fuzzy_match",
                        "gst_rate": gst,
                        "chapter": ch,
                        "heading": None,
                    },
                    "alternatives": [],
                    "confidence": score,
                    "confidence_label": label,
                    "needs_review": score < 0.55,
                    "processing_time_ms": 0.0,
                }
                nq = normalize_product_name(row.input_text)
                if not nq:
                    nq = (row.input_text or "").strip()
                if not nq:
                    continue
                cache_key = _match_cache_key(nq)
                await set_cache(cache_key, payload, ttl=_SYNONYM_FUZZY_CACHE_TTL_S)
                warmed += 1

        log.info("scheduler.synonym_fuzzy_cache_seed_done", distinct_queries=len(seen), entries_warmed=warmed)
    except Exception as exc:
        log.warning("scheduler.cache_seed_failed", error=str(exc))


async def start_scheduler():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        seed_synonym_fuzzy_cache_job,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="seed_synonym_fuzzy_cache",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    log.info("scheduler.started")


async def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
