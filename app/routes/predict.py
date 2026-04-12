from __future__ import annotations
import time
import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db, Prediction
from app.models.schemas import PredictRequest, PredictResponse
from app.services.matcher import get_matcher
from app.services.confidence import score_result
from app.utils.auth import require_api_key
from app.utils.cache import get_cache, set_cache
from app.utils.rate_limit import check_rate_limit

router = APIRouter(tags=["predict"])
log = structlog.get_logger()


@router.post("/predict", response_model=PredictResponse)
async def predict(
    body: PredictRequest,
    request: Request,
    api_key: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit(api_key)

    cache_key = f"predict:{body.text.strip().lower()}"
    cached = await get_cache(cache_key)
    if cached:
        log.info("predict.cache_hit", text=body.text[:50])
        return PredictResponse(**cached)

    start = time.perf_counter()
    matcher = get_matcher()
    matches = matcher.match(body.text, top_k=5)
    if not matches:
        raise HTTPException(status_code=422, detail="No HSN matches found for this description")

    top = matches[0]
    alternatives = matches[1:]
    confidence, label = score_result(top["score"])
    needs_review = top["score"] < 0.55

    request_id = str(uuid.uuid4())
    elapsed = (time.perf_counter() - start) * 1000

    record = Prediction(
        request_id=request_id,
        input_text=body.text,
        predicted_hsn=top["hsn_code"],
        confidence=confidence,
        needs_review=needs_review,
        api_key_hash=hash(api_key),
    )
    db.add(record)
    await db.commit()

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
