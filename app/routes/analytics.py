from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Branch, HsnCode, Prediction, User, UserRole, get_db
from app.routes.auth import require_role

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _branch_filter(current_user: User, branch_id_col):
    if current_user.role == UserRole.HQ_ADMIN.value:
        return True
    return branch_id_col == current_user.branch_id


@router.get("/overview")
async def overview(
    current_user: User = Depends(require_role(UserRole.BRANCH_MANAGER, UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    start_30 = now - timedelta(days=30)
    base_filter = _branch_filter(current_user, Prediction.branch_id)
    total_30 = (await db.execute(select(func.count(Prediction.id)).where(Prediction.created_at >= start_30, base_filter))).scalar() or 0
    today = now.date()
    today_count = (await db.execute(select(func.count(Prediction.id)).where(func.date(Prediction.created_at) == today, base_filter))).scalar() or 0
    avg_conf = (await db.execute(select(func.avg(Prediction.confidence)).where(Prediction.created_at >= start_30, base_filter))).scalar() or 0
    high = (await db.execute(select(func.count(Prediction.id)).where(Prediction.created_at >= start_30, Prediction.confidence >= 0.8, base_filter))).scalar() or 0
    low = (await db.execute(select(func.count(Prediction.id)).where(Prediction.created_at >= start_30, Prediction.confidence < 0.55, base_filter))).scalar() or 0
    top_rows = (
        await db.execute(
            select(Prediction.predicted_hsn, HsnCode.description, func.count(Prediction.id).label("cnt"))
            .join(HsnCode, HsnCode.hsn_code == Prediction.predicted_hsn, isouter=True)
            .where(Prediction.created_at >= start_30, base_filter)
            .group_by(Prediction.predicted_hsn, HsnCode.description)
            .order_by(func.count(Prediction.id).desc())
            .limit(5)
        )
    ).all()
    dist_rows = (
        await db.execute(
            select(HsnCode.gst_rate_numeric, func.count(Prediction.id))
            .join(HsnCode, HsnCode.hsn_code == Prediction.predicted_hsn, isouter=True)
            .where(Prediction.created_at >= start_30, base_filter)
            .group_by(HsnCode.gst_rate_numeric)
        )
    ).all()
    dist = {"0": 0, "5": 0, "12": 0, "18": 0, "28": 0}
    for r, c in dist_rows:
        if r is None:
            continue
        dist[str(int(float(r)))] = int(c)
    pending = (await db.execute(select(func.count(Prediction.id)).where(Prediction.needs_review == True, base_filter))).scalar() or 0  # noqa: E712
    return {
        "total_predictions_30d": int(total_30),
        "predictions_today": int(today_count),
        "avg_confidence": float(avg_conf),
        "high_confidence_pct": float(high / total_30 * 100) if total_30 else 0.0,
        "low_confidence_pct": float(low / total_30 * 100) if total_30 else 0.0,
        "top_5_hsn_codes": [{"hsn_code": r.predicted_hsn, "description": r.description, "count": int(r.cnt)} for r in top_rows],
        "gst_rate_distribution": dist,
        "pending_reviews": int(pending),
    }


@router.get("/trends")
async def trends(
    period: str = Query(default="30d"),
    current_user: User = Depends(require_role(UserRole.BRANCH_MANAGER, UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
    start = datetime.now(timezone.utc) - timedelta(days=days)
    base_filter = _branch_filter(current_user, Prediction.branch_id)
    rows = (
        await db.execute(
            select(func.date(Prediction.created_at).label("d"), func.count(Prediction.id).label("cnt"), func.avg(Prediction.confidence).label("avg"))
            .where(Prediction.created_at >= start, base_filter)
            .group_by(func.date(Prediction.created_at))
            .order_by(func.date(Prediction.created_at))
        )
    ).all()
    return [{"date": str(r.d), "count": int(r.cnt), "avg_confidence": float(r.avg or 0)} for r in rows]


@router.get("/branches/compare")
async def branches_compare(
    current_user: User = Depends(require_role(UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    start_30 = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (
        await db.execute(
            select(
                Branch.name,
                Branch.city,
                func.count(Prediction.id).label("predictions_30d"),
                func.avg(Prediction.confidence).label("avg_confidence"),
                func.sum(case((Prediction.needs_review == True, 1), else_=0)).label("pending_reviews"),  # noqa: E712
            )
            .join(Prediction, Prediction.branch_id == Branch.id, isouter=True)
            .where((Prediction.created_at.is_(None)) | (Prediction.created_at >= start_30))
            .group_by(Branch.id, Branch.name, Branch.city)
        )
    ).all()
    return [
        {
            "branch_name": r.name,
            "city": r.city,
            "predictions_30d": int(r.predictions_30d or 0),
            "avg_confidence": float(r.avg_confidence or 0),
            "pending_reviews": int(r.pending_reviews or 0),
        }
        for r in rows
    ]
