from __future__ import annotations
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Prediction, User, UserRole, get_db
from app.models.schemas import ResolveRequest, ReviewItem
from app.services.audit import EventType, log_event
from app.routes.auth import require_role

router = APIRouter(prefix="/review", tags=["review"])
log = structlog.get_logger()

# Role Access Table:
# - GET /review/pending: BRANCH_MANAGER, REGIONAL_ADMIN, HQ_ADMIN, AUDITOR
# - POST /review/resolve: BRANCH_MANAGER, REGIONAL_ADMIN, HQ_ADMIN


@router.get("/pending", response_model=list[ReviewItem])
async def get_pending(
    current_user: User = Depends(
        require_role(
            UserRole.BRANCH_MANAGER,
            UserRole.REGIONAL_ADMIN,
            UserRole.HQ_ADMIN,
            UserRole.AUDITOR,
        )
    ),
    db: AsyncSession = Depends(get_db),
):
    q = select(Prediction).where(
        Prediction.needs_review == True,
        Prediction.resolved == False,
    )
    if getattr(current_user, "role", None) != UserRole.HQ_ADMIN.value:
        q = q.where(Prediction.branch_id == current_user.branch_id)
    result = await db.execute(q.limit(100))
    rows = result.scalars().all()
    return [ReviewItem.model_validate(r) for r in rows]


@router.post("/resolve")
async def resolve_review(
    body: ResolveRequest,
    current_user: User = Depends(
        require_role(
            UserRole.BRANCH_MANAGER,
            UserRole.REGIONAL_ADMIN,
            UserRole.HQ_ADMIN,
        )
    ),
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
    old_status = "pending"
    pred.corrected_hsn = body.corrected_hsn
    pred.resolved = True
    await log_event(
        session=db,
        event_type=EventType.REVIEW_RESOLVED,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        branch_id=getattr(pred, "branch_id", None),
        entity_type="prediction",
        entity_id=str(pred.id),
        old_value={"status": old_status},
        new_value={"status": "resolved", "corrected_hsn": body.corrected_hsn, "resolved_by": str(current_user.id)},
    )
    await db.commit()
    log.info("review.resolved", request_id=body.request_id, corrected=body.corrected_hsn)
    return {"status": "resolved", "request_id": body.request_id}
