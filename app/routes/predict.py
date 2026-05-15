from __future__ import annotations
import hashlib
import inspect
import time
import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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

    cache_key = f"predict:{body.text.strip().lower()}"
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
        if not matches:
            matcher = get_matcher()
            matches = await matcher.amatch(search_text, top_k=5)
        if not matches:
            raise HTTPException(status_code=422, detail="No HSN matches found for this description")

        top = matches[0]
        alternatives = matches[1:]
        confidence, label = score_result(top["score"])
        needs_review = top["score"] < 0.55
        elapsed = (time.perf_counter() - start) * 1000

    try:
        record = Prediction(
            request_id=request_id,
            input_text=body.text,
            predicted_hsn=top["hsn_code"],
            confidence=confidence,
            needs_review=needs_review,
            api_key_hash=hashlib.sha256(api_key.encode()).hexdigest()[:16],
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
    await set_cache(cache_key, result.model_dump())
    return result
