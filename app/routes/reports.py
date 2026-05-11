from __future__ import annotations

import csv
import io
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Branch, HsnCode, Prediction, User, UserRole, get_db
from app.models.gst_rate_history import GSTRateHistory
from app.routes.auth import require_role
from app.services.report_generator import generate_gst_pdf

router = APIRouter(prefix="/reports", tags=["reports"])


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
    rows = (
        await db.execute(
            select(
                Prediction.predicted_hsn.label("hsn_code"),
                HsnCode.description.label("description"),
                HsnCode.gst_rate_numeric.label("gst_rate"),
                func.count(Prediction.id).label("transaction_count"),
            )
            .join(HsnCode, HsnCode.hsn_code == Prediction.predicted_hsn, isouter=True)
            .where(
                Prediction.branch_id == branch_id,
                Prediction.created_at >= from_date,
                Prediction.created_at <= to_date,
            )
            .group_by(Prediction.predicted_hsn, HsnCode.description, HsnCode.gst_rate_numeric)
        )
    ).all()
    payload = [
        {
            "hsn_code": r.hsn_code,
            "description": r.description,
            "gst_rate": float(r.gst_rate) if r.gst_rate is not None else None,
            "transaction_count": int(r.transaction_count),
            "effective_from": None,
            "effective_to": None,
        }
        for r in rows
    ]
    if format == "json":
        return payload
    if format == "csv":
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(payload[0].keys()) if payload else ["hsn_code", "description", "gst_rate", "transaction_count", "effective_from", "effective_to"])
        writer.writeheader()
        for row in payload:
            writer.writerow(row)
        return StreamingResponse(iter([out.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=gst_report_{branch_id}_{from_date}_{to_date}.csv"})
    if format == "pdf":
        branch = (await db.execute(select(Branch).where(Branch.id == branch_id))).scalars().first()
        pdf_bytes = generate_gst_pdf(payload, branch, f"{from_date} to {to_date}")
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
        )
    ).scalars().all()
    return [
        {
            "hsn_code": r.hsn_code,
            "gst_rate": r.gst_rate,
            "effective_from": r.effective_from,
            "effective_to": r.effective_to,
            "source_url": r.source_url,
        }
        for r in rows
    ]


@router.get("/gst/unclassified")
async def gst_unclassified(
    branch_id: UUID,
    current_user: User = Depends(require_role(UserRole.AUDITOR, UserRole.BRANCH_MANAGER, UserRole.REGIONAL_ADMIN, UserRole.HQ_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    if not _can_access_branch(current_user, branch_id):
        raise HTTPException(status_code=403, detail="Not allowed for this branch")
    rows = (
        await db.execute(
            select(Prediction).where(
                Prediction.branch_id == branch_id,
                and_(Prediction.confidence < 0.7, Prediction.needs_review == True),  # noqa: E712
            )
        )
    ).scalars().all()
    return [
        {
            "request_id": r.request_id,
            "input_text": r.input_text,
            "predicted_hsn": r.predicted_hsn,
            "confidence": r.confidence,
            "needs_review": r.needs_review,
            "created_at": r.created_at,
        }
        for r in rows
    ]
