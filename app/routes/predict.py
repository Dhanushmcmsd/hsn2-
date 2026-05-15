from __future__ import annotations
import hashlib
import inspect
import json
import re
import time
import uuid
import structlog
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import get_db, Prediction, VerifiedProduct
from app.models.schemas import PredictRequest, PredictResponse
from app.services.matcher import get_matcher, strip_sizes
from app.services.kerala_search import expand_kerala_query
from app.services.db_matcher import match_query
from app.services.confidence import score_result
from app.utils.auth import require_api_key
from app.utils.cache import get_cache, set_cache
from app.utils.rate_limit import check_rate_limit

router = APIRouter(tags=["predict"])
log = structlog.get_logger()

# ── Unified cache key format (same as main.py) ─────────────────────────────────
_QUERY_NORMALIZE_RE = re.compile(r"\s+")

_CLAUDE_CACHE_TTL_S = 86400
_LOW_SCORE_CLAUDE_THRESHOLD = 0.30
_HYBRID_OVERRUN_DB_THRESHOLD = 0.35

WARMING_UP_DETAIL = "Service warming up, retry in 2s"


def _normalize_query_for_cache(q: str) -> str:
    """Normalize query for cache key generation - matches main.py format."""
    return _QUERY_NORMALIZE_RE.sub(" ", (q or "").strip()).upper()


def _match_cache_key(query: str) -> str:
    """
    Unified cache key format for HSN matching results.
    Format: match:v1:<sha1 of normalized query>
    Matches main.py /predict and /hsn/batch endpoints.
    """
    norm = _normalize_query_for_cache(query)
    return "match:v1:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _extract_json_object(raw: str) -> dict | None:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


async def _claude_hsn_fallback(product_name: str) -> dict | None:
    key = (settings.ANTHROPIC_API_KEY or "").strip()
    if not key:
        return None
    prompt = (
        f"You are an Indian GST HSN code expert. Given the product name: '{product_name}', "
        "return ONLY a JSON object with keys: "
        "hsn_code (8-digit string), description (string), gst_rate (number, e.g. 18), "
        "chapter (2-digit string), confidence (number 0-100). "
        "Base your answer strictly on official Indian GST HSN classification rules. "
        "Return nothing else — no markdown, no explanation."
    )
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.ANTHROPIC_MODEL,
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            payload = r.json()
            text = payload["content"][0]["text"].strip()
    except Exception as exc:
        log.warning("predict.claude_request_failed", error=str(exc))
        return None

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)

    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _extract_json_object(text)

    if not isinstance(data, dict):
        log.warning("predict.claude_parse_failed", reason="not_object")
        return None

    hsn = re.sub(r"[^0-9]", "", str(data.get("hsn_code", "")))
    if len(hsn) < 4:
        log.warning("predict.claude_parse_failed", reason="bad_hsn")
        return None
    hsn = hsn.zfill(8)[:8]

    desc = str(data.get("description") or "").strip()
    if not desc:
        desc = product_name.strip()

    try:
        gst_rate = float(data.get("gst_rate"))
    except (TypeError, ValueError):
        gst_rate = 0.0

    chapter_raw = str(data.get("chapter") or "").strip()
    chapter = re.sub(r"[^0-9]", "", chapter_raw)[:2]
    if len(chapter) < 2 and len(hsn) >= 2:
        chapter = hsn[:2]

    try:
        conf_pct = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        conf_pct = 0.0
    conf_pct = max(0.0, min(100.0, conf_pct))
    score = round(conf_pct / 100.0, 4)

    return {
        "hsn_code": hsn,
        "description": desc,
        "gst_rate": gst_rate,
        "score": score,
        "method": "claude_fallback",
        "chapter": chapter if len(chapter) == 2 else None,
    }


async def _scalar_one_or_none(result):
    value = result.scalar_one_or_none()
    if inspect.isawaitable(value):
        value = await value
    return value


def _is_verified_product_match(candidate) -> bool:
    return isinstance(getattr(candidate, "hsn_code", None), str) and isinstance(
        getattr(candidate, "description", None), str
    )


async def _fetch_verified_single_pass(db: AsyncSession, body_text: str):
    """One round-trip for exact / Kerala-expanded / no-size verified rows (priority preserved)."""
    normalized = body_text.upper().strip()
    no_size_val = strip_sizes(body_text)
    try:
        kerala_expanded = expand_kerala_query(body_text)
    except Exception as exc:
        log.info("predict.kerala_expand_unavailable", error=str(exc))
        kerala_expanded = body_text
    kerala_norm = kerala_expanded.upper().strip()

    priority = case(
        (VerifiedProduct.description_normalized == normalized, 1),
        (VerifiedProduct.description_normalized == kerala_norm, 2),
        (VerifiedProduct.description_no_size == no_size_val, 3),
        else_=4,
    )
    stmt = (
        select(VerifiedProduct)
        .where(
            or_(
                VerifiedProduct.description_normalized == normalized,
                VerifiedProduct.description_normalized == kerala_norm,
                VerifiedProduct.description_no_size == no_size_val,
            )
        )
        .order_by(priority)
        .limit(1)
    )
    try:
        verified_result = await db.execute(stmt)
        return await _scalar_one_or_none(verified_result), normalized, kerala_norm, no_size_val
    except Exception as exc:
        log.info("predict.verified_combined_unavailable", error=str(exc))
        return None, normalized, kerala_norm, no_size_val


def _verified_score_method(verified, normalized: str, kerala_norm: str, no_size_val: str) -> tuple[float, str]:
    if verified.description_normalized == normalized:
        return 1.0, "verified_exact"
    if verified.description_normalized == kerala_norm:
        return 0.92, "verified_kerala_expanded"
    if verified.description_no_size == no_size_val:
        return 0.95, "verified_no_size"
    return 1.0, "verified_exact"


@router.post("/predict", response_model=PredictResponse)
async def predict(
    body: PredictRequest,
    request: Request,
    api_key: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit(api_key)
    if not getattr(request.app.state, "ready", True):
        raise HTTPException(status_code=503, detail=WARMING_UP_DETAIL)

    request_id = str(uuid.uuid4())

    # Use unified cache key format (same as main.py /predict and /hsn/batch)
    cache_key = _match_cache_key(body.text)
    cached = await get_cache(cache_key)
    if cached:
        log.info("predict.cache_hit", text=body.text[:50])
        return PredictResponse(**cached)

    start = time.perf_counter()

    search_text = body.text
    try:
        from app.services import aliases as alias_svc

        expanded = await alias_svc.expand_query(db, body.text)
        if expanded.english_query and expanded.english_query.strip():
            search_text = expanded.english_query.strip()
    except Exception as exc:
        log.info("predict.alias_expand_skipped", error=str(exc))

    verified = None
    try:
        verified, normalized, kerala_norm, no_size_val = await _fetch_verified_single_pass(db, search_text)
    except Exception as exc:
        log.info("predict.verified_fetch_failed", error=str(exc))
        verified, normalized, kerala_norm, no_size_val = None, body.text.upper().strip(), "", ""

    prediction_source: str | None = None

    if _is_verified_product_match(verified):
        score, method = _verified_score_method(verified, normalized, kerala_norm, no_size_val)
        top = {
            "hsn_code": verified.hsn_code,
            "description": verified.description,
            "gst_rate": float(verified.gst_rate or 0) if verified.gst_rate else None,
            "score": score,
            "method": method,
        }
        alternatives = []
        confidence, label = score_result(score)
        needs_review = False
        elapsed = (time.perf_counter() - start) * 1000
    else:
        matches = await match_query(search_text, db, top_k=5)
        matcher = get_matcher()
        if matcher.ready:
            if not matches or matches[0].get("score", 0) < _HYBRID_OVERRUN_DB_THRESHOLD:
                hybrid = await matcher.amatch(search_text, top_k=5)
                if hybrid and (
                    not matches or hybrid[0].get("score", 0) > matches[0].get("score", 0)
                ):
                    matches = hybrid
        elif not matches:
            matches = await matcher.amatch(search_text, top_k=5)

        if not matches:
            raise HTTPException(status_code=422, detail="No HSN matches found for this description")

        top = matches[0]
        alternatives = matches[1:]
        confidence, label = score_result(top["score"])
        needs_review = top["score"] < 0.55
        elapsed = (time.perf_counter() - start) * 1000

        if (
            top["score"] < _LOW_SCORE_CLAUDE_THRESHOLD
            and getattr(request.app.state, "ready", True)
        ):
            claude_top = await _claude_hsn_fallback(search_text)
            if claude_top:
                top = claude_top
                alternatives = []
                confidence, label = score_result(top["score"])
                needs_review = top["score"] < 0.55
                prediction_source = "claude_fallback"
                elapsed = (time.perf_counter() - start) * 1000
                log.info("predict.claude_fallback_used", text=body.text[:60])

    try:
        record = Prediction(
            request_id=request_id,
            input_text=body.text,
            predicted_hsn=top["hsn_code"],
            confidence=confidence,
            needs_review=needs_review,
            api_key_hash=hashlib.sha256(api_key.encode()).hexdigest()[:16],
            source=prediction_source,
        )
        db.add(record)
        await db.commit()
    except Exception as exc:
        log.info("predict.persistence_unavailable", error=str(exc))
        try:
            await db.rollback()
        except Exception:
            pass

    result = PredictResponse(
        request_id=request_id,
        input_text=body.text,
        top_match=top,
        alternatives=alternatives,
        confidence=confidence,
        confidence_label=label,
        needs_review=needs_review,
        processing_time_ms=round(elapsed, 1),
    )
    cache_ttl = _CLAUDE_CACHE_TTL_S if prediction_source == "claude_fallback" else None
    await set_cache(cache_key, result.model_dump(), ttl=cache_ttl)
    return result
