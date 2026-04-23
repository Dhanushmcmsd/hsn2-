from __future__ import annotations
import hashlib
import inspect
import time
import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db, Prediction, VerifiedProduct
from app.models.schemas import PredictRequest, PredictResponse
from app.services.matcher import get_matcher, strip_sizes
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

    # Pass 0: Check verified_products for exact / no-size match when available
    from sqlalchemy import select
    verified = None
    try:
        verified_query = select(VerifiedProduct).where(
            VerifiedProduct.description_normalized == body.text.upper().strip()
        )
        verified_result = await db.execute(verified_query)
        verified = await _scalar_one_or_none(verified_result)
    except Exception as exc:
        log.info("predict.verified_exact_unavailable", error=str(exc))

    if _is_verified_product_match(verified):
        top = {
            "hsn_code": verified.hsn_code,
            "description": verified.description,
            "gst_rate": float(verified.gst_rate or 0) if verified.gst_rate else None,
            "score": 1.0,
            "method": "verified_exact",
        }
        alternatives = []
        confidence, label = score_result(1.0)
        needs_review = False
        elapsed = (time.perf_counter() - start) * 1000
    else:
        verified = None
        try:
            verified_no_size_query = select(VerifiedProduct).where(
                VerifiedProduct.description_no_size == strip_sizes(body.text)
            )
            verified_no_size_result = await db.execute(verified_no_size_query)
            verified = await _scalar_one_or_none(verified_no_size_result)
        except Exception as exc:
            log.info("predict.verified_no_size_unavailable", error=str(exc))

        if _is_verified_product_match(verified):
            top = {
                "hsn_code": verified.hsn_code,
                "description": verified.description,
                "gst_rate": float(verified.gst_rate or 0) if verified.gst_rate else None,
                "score": 0.95,
                "method": "verified_no_size",
            }
            alternatives = []
            confidence, label = score_result(0.95)
            needs_review = False
            elapsed = (time.perf_counter() - start) * 1000
        else:
            # Pass 1+: upgraded DB-backed matching, then local matcher fallback
            matches = await match_query(body.text, db, top_k=5)
            if not matches:
                matcher = get_matcher()
                matches = matcher.match(body.text, top_k=5)
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
