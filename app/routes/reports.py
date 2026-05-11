from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Branch, Prediction, User, UserRole, get_db
from app.models.gst_rate_history import GSTRateHistory
from app.utils.auth import require_role
from app.services.dataset import get_dataset
from app.services.report_generator import generate_gst_pdf

router = APIRouter(tags=["reports"])


def _can_access_branch(current_user: User, branch_id: UUID) -> bool:
    if current_user.role == UserRole.HQ_ADMIN.value:
        return True
    return current_user.branch_id == branch_id


@router.get("/gst/summary")
async def gst_summary(
    branch_id: UUID,
    from_date: date,
    to_date: date,
    format: str = Query(default="json"),
    current_user: User = Depends(require_role(UserRole.BRANCH_MANAGER, UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    if not _can_access_branch(current_user, branch_id):
        raise HTTPException(status_code=403, detail="Not allowed for this branch")
    start_dt = datetime.combine(from_date, time.min).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(to_date + timedelta(days=1), time.min).replace(tzinfo=timezone.utc)
    normalized_format = format.strip().lower()
    rows = (
        await db.execute(
            select(
                Prediction.predicted_hsn.label("hsn_code"),
                func.count(Prediction.id).label("transaction_count"),
            )
            .where(
                Prediction.branch_id == branch_id,
                Prediction.created_at >= start_dt,
                Prediction.created_at < end_dt,
            )
            .group_by(Prediction.predicted_hsn)
            .order_by(func.count(Prediction.id).desc())
        )
    ).all()
    dataset_lookup = {
        row.get("hsn_code"): {
            "description": row.get("description", ""),
            "gst_rate": row.get("gst_rate"),
        }
        for row in get_dataset()
    }
    payload = [
        {
            "hsn_code": r.hsn_code,
            "description": dataset_lookup.get(r.hsn_code, {}).get("description", ""),
            "gst_rate": dataset_lookup.get(r.hsn_code, {}).get("gst_rate"),
            "transaction_count": int(r.transaction_count),
        }
        for r in rows
    ]
    if normalized_format == "json":
        return payload
    if normalized_format == "csv":
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(payload[0].keys()) if payload else ["hsn_code", "description", "gst_rate", "transaction_count"])
        writer.writeheader()
        for row in payload:
            writer.writerow(row)
        return StreamingResponse(iter([out.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=gst_report_{branch_id}_{from_date}_{to_date}.csv"})
    if normalized_format == "pdf":
        branch = (await db.execute(select(Branch).where(Branch.id == branch_id))).scalars().first()
        if branch is None:
            raise HTTPException(status_code=404, detail="Branch not found")
        pdf_bytes = generate_gst_pdf(payload, branch.name, branch.gstin or "N/A", f"{from_date} to {to_date}")
        return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=gst_report.pdf"})
    raise HTTPException(status_code=422, detail="format must be json|csv|pdf")


@router.get("/gst/rate-changes")
async def gst_rate_changes(
    branch_id: UUID,
    from_date: date,
    to_date: date,
    current_user: User = Depends(require_role(UserRole.BRANCH_MANAGER, UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    if not _can_access_branch(current_user, branch_id):
        raise HTTPException(status_code=403, detail="Not allowed for this branch")
    branch_hsns = (
        await db.execute(select(Prediction.predicted_hsn).where(Prediction.branch_id == branch_id).distinct())
    ).scalars().all()
    if not branch_hsns:
        return []
    rows = (
        await db.execute(
            select(GSTRateHistory).where(
                GSTRateHistory.hsn_code.in_(branch_hsns),
                GSTRateHistory.effective_from >= from_date,
                GSTRateHistory.effective_from <= to_date,
            )
            .order_by(GSTRateHistory.effective_from.desc())
        )
    ).scalars().all()
    return [
        {
            "hsn_code": r.hsn_code,
            "old_rate": None,
            "new_rate": r.gst_rate,
            "effective_from": r.effective_from,
            "effective_to": r.effective_to,
        }
        for r in rows
    ]


@router.get("/gst/unclassified")
async def gst_unclassified(
    branch_id: UUID,
    from_date: date,
    to_date: date,
    current_user: User = Depends(require_role(UserRole.AUDITOR, UserRole.BRANCH_MANAGER, UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    if not _can_access_branch(current_user, branch_id):
        raise HTTPException(status_code=403, detail="Not allowed for this branch")
    start_dt = datetime.combine(from_date, time.min).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(to_date + timedelta(days=1), time.min).replace(tzinfo=timezone.utc)
    rows = (
        await db.execute(
            select(Prediction).where(
                Prediction.branch_id == branch_id,
                Prediction.created_at >= start_dt,
                Prediction.created_at < end_dt,
                or_(Prediction.confidence < 0.7, Prediction.needs_review == True),  # noqa: E712
            )
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "product_description": r.input_text,
            "hsn_code": r.predicted_hsn,
            "confidence": r.confidence,
            "created_at": r.created_at,
        }
        for r in rows
    ]
