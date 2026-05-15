from __future__ import annotations
import hashlib
import inspect
import re
import time
import uuid
import structlog
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db, Prediction, VerifiedProduct
from app.models.schemas import PredictRequest, PredictResponse
from app.services.matcher import get_matcher, strip_sizes
from app.services.kerala_search import expand_kerala_query
from app.services.db_matcher import match_query
from app.services.confidence import score_result
from app.services.normalizer import normalize_product_name
from app.services.product_search import search_by_product_name, search_by_token_ilike, search_in_memory
from app.services import inverted_index
from app.services.brand_search import brand_lookup, is_unclassified_hsn
from app.utils.auth import require_api_key
from app.utils.cache import get_cache, set_cache
from app.utils.rate_limit import check_rate_limit

router = APIRouter(tags=["predict"])
log = structlog.get_logger()

# ── Unified cache key format (same as main.py) ─────────────────────────────────
_QUERY_NORMALIZE_RE = re.compile(r"\s+")

_SYNONYM_FUZZY_CACHE_TTL_S = 86400
_LOW_SCORE_SYNONYM_RESCUE_THRESHOLD = 0.30
_HYBRID_OVERRUN_DB_THRESHOLD = 0.35

def _normalize_confidence(score: float, source: str) -> int:
    """
    Normalizes raw layer scores to a consistent 0–100 integer for UI display.
    """
    ranges = {
        "exact":              (1.0, 1.0),
        "verified_exact":     (0.92, 1.0),
        "inverted_index":     (0.0, 1.0),
        "trigram":            (0.0, 1.0),
        "faiss":              (0.0, 1.0),
        "synonym_fuzzy":      (0.0, 1.0),
        "product_trigram":    (0.0, 1.0),
        "product_ilike":      (0.0, 1.0),
        "product_rapidfuzz":  (0.0, 1.0),
    }
    low, high = ranges.get(source, (0.0, 1.0))
    if high == low:
        return 100
    normalized = (score - low) / (high - low)
    return min(100, max(0, round(normalized * 100)))


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

    request_id = str(uuid.uuid4())

    normalized_query = normalize_product_name(body.text)
    if not normalized_query:
        normalized_query = (body.text or "").strip()
    if not normalized_query:
        raise HTTPException(status_code=422, detail="Product description is empty")

    cache_key = _match_cache_key(normalized_query)
    cached = await get_cache(cache_key)
    if cached:
        log.info("predict.cache_hit", text=body.text[:50])
        return PredictResponse(**cached)

    start = time.perf_counter()

    search_text = normalized_query
    try:
        from app.services import aliases as alias_svc

        expanded = await alias_svc.expand_query(db, normalized_query)
        if expanded.english_query and expanded.english_query.strip():
            search_text = expanded.english_query.strip()
    except Exception as exc:
        log.info("predict.alias_expand_skipped", error=str(exc))

    # ── Tier-0: Brand alias / brand-column lookup (fastest, most precise) ────
    # Runs BEFORE the verified_products exact match to catch brand-name-only
    # queries like "BOOST", "HORLICKS", "COLGATE" that would otherwise fall
    # through to low-confidence FAISS / synonym rescue paths.
    brand_result: dict | None = None
    try:
        brand_result = await brand_lookup(db, search_text, min_score=0.50)
    except Exception as exc:
        log.info("predict.brand_lookup_failed", error=str(exc))

    if brand_result and not is_unclassified_hsn(brand_result.get("hsn_code")):
        top = brand_result
        alternatives = []
        confidence, label = score_result(top["score"])
        needs_review = False
        prediction_source = top.get("method", "brand_lookup")
        elapsed = (time.perf_counter() - start) * 1000
        result = top

        # Persist and cache so subsequent identical queries are instant
        norm_conf = _normalize_confidence(top["score"], prediction_source)
        cache_payload = {
            "hsn_code":    top["hsn_code"],
            "description": top["description"],
            "gst_rate":    top["gst_rate"],
            "source":      prediction_source,
            "confidence":  norm_conf,
        }
        await set_cache(cache_key, cache_payload, ttl=86400)
        log.info("predict.brand_hit", query=body.text[:60], hsn=top["hsn_code"], method=prediction_source)

        record = Prediction(
            request_id=request_id,
            input_text=body.text,
            predicted_hsn=top["hsn_code"],
            confidence=norm_conf,
            needs_review=False,
            api_key_hash=hashlib.sha256(api_key.encode()).hexdigest()[:16],
            source=prediction_source,
        )
        try:
            db.add(record)
            await db.commit()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

        return PredictResponse(
            request_id=request_id,
            input_text=body.text,
            top_match=top,
            alternatives=[],
            confidence=norm_conf,
            confidence_label=label,
            needs_review=False,
            processing_time_ms=round(elapsed, 1),
        )

    verified = None
    try:
        verified, normalized, kerala_norm, no_size_val = await _fetch_verified_single_pass(db, search_text)
    except Exception as exc:
        log.info("predict.verified_fetch_failed", error=str(exc))
        verified, normalized, kerala_norm, no_size_val = None, search_text.upper().strip(), "", ""

    prediction_source: str | None = None

    if _is_verified_product_match(verified):
        score, method = _verified_score_method(verified, normalized, kerala_norm, no_size_val)
        top = {
            "hsn_code": verified.hsn_code,
            "description": verified.description,
            "gst_rate": float(verified.gst_rate or 0) if verified.gst_rate else None,
            "score": score,
            "method": method,
            "source": method,
        }
        alternatives = []
        confidence, label = score_result(score)
        needs_review = False
        prediction_source = method
        elapsed = (time.perf_counter() - start) * 1000
    else:
        matches = []
        matcher = None
        inv_matches = await inverted_index.search(db, search_text, limit=5)
        if inv_matches and inv_matches[0].get("score", 0) >= 0.50:
            top = inv_matches[0]
            top.setdefault("source", "inverted_index")
            alternatives = inv_matches[1:]
            confidence, label = score_result(top["score"])
            needs_review = top["score"] < 0.55
            prediction_source = "inverted_index"
            elapsed = (time.perf_counter() - start) * 1000
        else:
            trgm_matches = await inverted_index.fuzzy_trgm(db, search_text, limit=5)
            if trgm_matches and trgm_matches[0].get("score", 0) >= 0.40:
                top = trgm_matches[0]
                top.setdefault("source", "trigram")
                alternatives = trgm_matches[1:]
                confidence, label = score_result(top["score"])
                needs_review = top["score"] < 0.55
                prediction_source = "trigram"
                elapsed = (time.perf_counter() - start) * 1000
            else:
                matches = await match_query(search_text, db, top_k=5)
                matcher = get_matcher()
        if matcher and matcher.ready:
            if not matches or matches[0].get("score", 0) < _HYBRID_OVERRUN_DB_THRESHOLD:
                hybrid = await matcher.amatch(search_text, top_k=5)
                if hybrid and (
                    not matches or hybrid[0].get("score", 0) > matches[0].get("score", 0)
                ):
                    matches = hybrid
        elif matcher and not matches:
            matches = await matcher.amatch(search_text, top_k=5)

        if not matches:
            raise HTTPException(status_code=422, detail="No HSN matches found for this description")

        top = matches[0]
        alternatives = matches[1:]
        top.setdefault("source", prediction_source or "hsn_codes")
        confidence, label = score_result(top["score"])
        needs_review = top["score"] < 0.55
        prediction_source = top.get("source") or top.get("method")
        elapsed = (time.perf_counter() - start) * 1000

        if (
            top["score"] < _LOW_SCORE_SYNONYM_RESCUE_THRESHOLD
            and getattr(request.app.state, "ready", True)
        ):
            rescue = await asyncio.to_thread(
                matcher.synonym_fuzzy_rescue,
                search_text,
                float(top["score"]),
            )
            if rescue:
                top = rescue
                alternatives = []
                confidence, label = score_result(top["score"])
                needs_review = top["score"] < 0.55
                prediction_source = "synonym_fuzzy_match"
                elapsed = (time.perf_counter() - start) * 1000
                log.info("predict.synonym_fuzzy_rescue_used", text=body.text[:60])

    result = top

    # ── Error boundary: reject 99999999 for known brands ──────────────────────
    # If all search tiers returned 99999999 / unclassified but we have a brand
    # alias hit, use the alias result rather than returning the catch-all code.
    if is_unclassified_hsn(result.get("hsn_code")) and brand_result:
        result = brand_result
        top = brand_result
        alternatives = []
        confidence, label = score_result(brand_result["score"])
        needs_review = True
        prediction_source = brand_result.get("method", "brand_lookup_fallback")
        elapsed = (time.perf_counter() - start) * 1000
        log.warning(
            "predict.unclassified_rescued_by_brand",
            query=body.text[:60],
            hsn=brand_result["hsn_code"],
        )

    # ── NEW: Product Name Search Layer ────────────
    if not result or result.get("score", 0) < 0.30:
        product_result = await search_by_product_name(db, body.text)
        if not product_result:
            product_result = await search_by_token_ilike(db, body.text)
        if not product_result:
            product_result = search_in_memory(body.text, getattr(request.app.state, "product_name_cache", []))

        if product_result:
            result = product_result
            top = product_result
            alternatives = []
            confidence, label = score_result(result["score"])
            needs_review = result["score"] < 0.55
            prediction_source = result["source"]
            elapsed = (time.perf_counter() - start) * 1000

            # Fix D: cache immediately so second (and all future) requests
            # skip every search layer entirely and return in < 5ms
            norm_conf = _normalize_confidence(result["score"], result["source"])
            cache_payload = {
                "hsn_code":    result["hsn_code"],
                "description": result["description"],
                "gst_rate":    result["gst_rate"],
                "source":      result["source"],
                "confidence":  norm_conf
            }
            await set_cache(
                key=cache_key,
                value=cache_payload,
                ttl=86400
            )

            # Also insert into predictions table for review/scheduler
            from sqlalchemy import text
            try:
                await db.execute(text("""
                    INSERT INTO predictions (request_id, input_text, predicted_hsn, confidence, source, created_at)
                    VALUES (:req, :input, :hsn, :conf, :src, NOW())
                    ON CONFLICT DO NOTHING
                """), {
                    "req": request_id,
                    "input": body.text,
                    "hsn":   result["hsn_code"],
                    "conf":  norm_conf,
                    "src":   result["source"]
                })
                await db.commit()
            except Exception as exc:
                log.warning("predict.product_insert_failed", error=str(exc))
                try:
                    await db.rollback()
                except Exception:
                    pass

    # Normalize confidence across all layers
    result_source = prediction_source or result.get("source") or result.get("method") or "unknown"
    result["source"] = result_source
    confidence = _normalize_confidence(result["score"], result_source)
    label = score_result(result["score"])[1]
    prediction_source = result_source

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
        log.warning("predict.persistence_unavailable", error=str(exc))
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
    cache_ttl = None
    if prediction_source == "synonym_fuzzy_match" and confidence >= 0.55:
        cache_ttl = _SYNONYM_FUZZY_CACHE_TTL_S
    await set_cache(cache_key, result.model_dump(), ttl=cache_ttl)
    return result
