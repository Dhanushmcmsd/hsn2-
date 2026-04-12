from __future__ import annotations
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db, Prediction
from app.models.schemas import ResolveRequest, ReviewItem
from app.utils.auth import require_api_key

router = APIRouter(prefix="/review", tags=["review"])
log = structlog.get_logger()


@router.get("/pending", response_model=list[ReviewItem])
async def get_pending(
    api_key: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Prediction).where(
            Prediction.needs_review == True,
            Prediction.resolved == False,
        ).limit(100)
    )
    rows = result.scalars().all()
    return [ReviewItem.model_validate(r) for r in rows]


@router.post("/resolve")
async def resolve_review(
    body: ResolveRequest,
    api_key: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Prediction).where(Prediction.request_id == body.request_id)
    )
    pred = result.scalar_one_or_none()
    if not pred:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if pred.resolved:
        raise HTTPException(status_code=409, detail="Already resolved")
    pred.corrected_hsn = body.corrected_hsn
    pred.resolved = True
    await db.commit()
    log.info("review.resolved", request_id=body.request_id, corrected=body.corrected_hsn)
    return {"status": "resolved", "request_id": body.request_id}
