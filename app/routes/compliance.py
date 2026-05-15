"""Government compliance endpoints — for GOI/CBIC submission readiness.

Endpoints (additive — no existing routes affected):
  GET  /api/v1/compliance/stats         — accuracy metrics dashboard (admin)
  GET  /api/v1/compliance/export/hsn    — full HSN report CSV/JSON (admin)
  POST /api/v1/compliance/validate      — validate HSN/GST pair
  GET  /api/v1/compliance/audit-log     — data audit trail (admin)
  GET  /api/v1/compliance/coverage      — chapter coverage stats (admin)
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.database import get_db
from app.services.hsn_validator import validate_hsn_gst_pair
from app.utils.auth import require_api_key, require_admin_key

router = APIRouter(prefix="/api/v1/compliance", tags=["GST Compliance"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ValidateRequest(BaseModel):
    hsn_code: str
    gst_rate: Optional[float] = None


class ValidateResponse(BaseModel):
    is_valid: bool
    hsn_code: str
    gst_rate: Optional[float]
    chapter: Optional[str]
    heading: Optional[str]
    subheading: Optional[str]
    errors: list[str]
    warnings: list[str]
    amendment_note: Optional[str]
    cess_likely_applicable: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/validate", response_model=ValidateResponse, summary="Validate HSN code and GST rate")
async def validate_hsn(
    body: ValidateRequest,
    _key: str = Depends(require_api_key),
) -> ValidateResponse:
    """
    Validate an HSN code and optional GST rate against CBIC rules.

    Checks:
    - HSN format (2/4/6/8 digit)
    - GST rate validity (0, 0.1, 0.25, 1.5, 3, 5, 12, 18, 28 only)
    - Known amendments and reclassifications
    - Cess applicability
    """
    result = validate_hsn_gst_pair(body.hsn_code, body.gst_rate)
    return ValidateResponse(**result)


@router.get("/stats", summary="Accuracy metrics dashboard (admin)")
async def compliance_stats(
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_admin_key),
) -> dict:
    """Returns the compliance readiness metrics for GOI submission."""
    stats: dict = {}

    try:
        # Total HSN codes
        stats["hsn_master_total"] = (
            await db.execute(text("SELECT COUNT(*) FROM hsn_master"))
        ).scalar() or 0

        # Active HSN codes
        stats["hsn_master_active"] = (
            await db.execute(text("SELECT COUNT(*) FROM hsn_master WHERE is_active = TRUE"))
        ).scalar() or 0

        # HSN coverage by chapter
        chapter_rows = (await db.execute(text("""
            SELECT chapter, COUNT(*) AS count
            FROM hsn_master
            WHERE chapter IS NOT NULL
            GROUP BY chapter
            ORDER BY chapter
        """))).mappings().all()
        stats["coverage_by_chapter"] = {str(r["chapter"]): r["count"] for r in chapter_rows}

        # Chapters covered
        stats["chapters_covered"] = len(stats["coverage_by_chapter"])
        stats["chapters_total"] = 99

        # Brand aliases
        stats["brand_aliases_total"] = (
            await db.execute(text("SELECT COUNT(*) FROM brand_aliases"))
        ).scalar() or 0
        stats["brand_aliases_active"] = (
            await db.execute(text("SELECT COUNT(*) FROM brand_aliases WHERE is_active = TRUE"))
        ).scalar() or 0

        # Verified products
        stats["verified_products_total"] = (
            await db.execute(text("SELECT COUNT(*) FROM verified_products"))
        ).scalar() or 0

        # Search cache
        stats["search_cache_total"] = (
            await db.execute(text("SELECT COUNT(*) FROM search_cache"))
        ).scalar() or 0
        stats["search_cache_active"] = (
            await db.execute(text(
                "SELECT COUNT(*) FROM search_cache WHERE expires_at IS NULL OR expires_at > NOW()"
            ))
        ).scalar() or 0

        # Pending review
        stats["pending_review_count"] = (
            await db.execute(text("SELECT COUNT(*) FROM pending_review WHERE status = 'pending'"))
        ).scalar() or 0

        # Tier distribution from search_cache
        tier_rows = (await db.execute(text("""
            SELECT tier_used, COUNT(*) AS count
            FROM search_cache
            WHERE tier_used IS NOT NULL
            GROUP BY tier_used
            ORDER BY tier_used
        """))).mappings().all()
        stats["tier_distribution"] = {str(r["tier_used"]): r["count"] for r in tier_rows}

        # HSN codes with GST rate issues (NULL rate)
        stats["hsn_missing_gst_rate"] = (
            await db.execute(text(
                "SELECT COUNT(*) FROM hsn_master WHERE gst_rate IS NULL AND is_active = TRUE"
            ))
        ).scalar() or 0

        # Language aliases
        stats["language_aliases_total"] = (
            await db.execute(text("SELECT COUNT(*) FROM language_aliases"))
        ).scalar() or 0

        # HSN codes table
        stats["hsn_codes_total"] = (
            await db.execute(text("SELECT COUNT(*) FROM hsn_codes"))
        ).scalar() or 0

        stats["generated_at"] = datetime.now(timezone.utc).isoformat()
        stats["compliance_score"] = _compute_compliance_score(stats)

    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Stats query failed: {exc}")

    return stats


def _compute_compliance_score(stats: dict) -> float:
    """Rough compliance readiness score (0-100)."""
    score = 0.0
    if stats.get("hsn_master_total", 0) >= 100:
        score += 25
    if stats.get("brand_aliases_total", 0) >= 100:
        score += 25
    if stats.get("chapters_covered", 0) >= 30:
        score += 25
    if stats.get("pending_review_count", 999) <= 50:
        score += 15
    if stats.get("hsn_missing_gst_rate", 999) == 0:
        score += 10
    return min(100.0, score)


@router.get("/coverage", summary="Chapter coverage stats (admin)")
async def coverage_stats(
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_admin_key),
) -> dict:
    """Returns per-chapter HSN coverage stats."""
    try:
        rows = (await db.execute(text("""
            SELECT
                chapter,
                COUNT(*) AS total,
                SUM(CASE WHEN gst_rate IS NOT NULL THEN 1 ELSE 0 END) AS with_gst,
                SUM(CASE WHEN cess_applicable = TRUE THEN 1 ELSE 0 END) AS with_cess,
                MAX(last_updated) AS last_updated
            FROM hsn_master
            WHERE chapter IS NOT NULL
            GROUP BY chapter
            ORDER BY chapter
        """))).mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB error: {exc}")

    return {
        "chapters": [
            {
                "chapter": r["chapter"],
                "total": r["total"],
                "with_gst_rate": r["with_gst"],
                "with_cess": r["with_cess"],
                "coverage_pct": round((r["with_gst"] / r["total"]) * 100, 1) if r["total"] else 0,
                "last_updated": str(r["last_updated"]) if r.get("last_updated") else None,
            }
            for r in rows
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/export/hsn", summary="Export full HSN report (admin)")
async def export_hsn_report(
    format: str = Query("csv", enum=["csv", "json"], description="Export format"),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_admin_key),
) -> StreamingResponse:
    """
    Export the complete HSN code report for GOI/CBIC submission.

    Returns all HSN codes with:
    - HSN code (8-digit)
    - Description (CBIC official)
    - GST rate
    - Cess applicable
    - Chapter number
    - Category
    - Verified source (CBIC notification reference)
    - Last updated timestamp
    """
    try:
        rows = (await db.execute(text("""
            SELECT
                hsn_code,
                description,
                gst_rate,
                cess_applicable,
                chapter,
                category,
                notes,
                verified_source,
                last_updated,
                is_active
            FROM hsn_master
            ORDER BY chapter, hsn_code
        """))).mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Export query failed: {exc}")

    if format == "json":
        import json
        data = [
            {
                "hsn_code": r["hsn_code"],
                "description": r["description"],
                "gst_rate": float(r["gst_rate"]) if r["gst_rate"] is not None else None,
                "cess_applicable": bool(r["cess_applicable"]),
                "chapter": r["chapter"],
                "category": r["category"],
                "notes": r.get("notes"),
                "verified_source": r.get("verified_source"),
                "last_updated": str(r["last_updated"]) if r.get("last_updated") else None,
                "is_active": bool(r["is_active"]),
            }
            for r in rows
        ]
        content = json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_records": len(data),
                "source": "CBIC HSN Master 2024-25",
                "hsn_codes": data,
            },
            ensure_ascii=False,
            indent=2,
        )
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=hsn_report.json"},
        )

    # CSV format
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "HSN Code", "Description", "GST Rate (%)", "Cess Applicable",
        "Chapter", "Category", "Verified Source", "Last Updated", "Active",
    ])
    for r in rows:
        writer.writerow([
            r["hsn_code"],
            r["description"],
            r["gst_rate"] if r["gst_rate"] is not None else "",
            "Yes" if r["cess_applicable"] else "No",
            r["chapter"] if r["chapter"] else "",
            r["category"] if r["category"] else "",
            r.get("verified_source") or "",
            str(r["last_updated"]) if r.get("last_updated") else "",
            "Yes" if r["is_active"] else "No",
        ])

    content_str = output.getvalue()
    return StreamingResponse(
        iter([content_str]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=hsn_report_{datetime.now().strftime('%Y%m%d')}.csv"
        },
    )


@router.get("/audit-log", summary="Data audit trail (admin)")
async def get_audit_log(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    table_name: Optional[str] = Query(None, description="Filter by table name"),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_admin_key),
) -> dict:
    """Returns the audit trail for all HSN data changes."""
    try:
        where_clause = "WHERE 1=1"
        params: dict = {"limit": limit, "offset": offset}
        if table_name:
            where_clause += " AND table_name = :table_name"
            params["table_name"] = table_name

        rows = (await db.execute(text(f"""
            SELECT id, table_name, record_id, product_name,
                   old_hsn, new_hsn, old_gst, new_gst,
                   change_reason, source_reference, changed_at
            FROM brand_hsn_enrichment_log
            {where_clause}
            ORDER BY changed_at DESC
            LIMIT :limit OFFSET :offset
        """), params)).mappings().all()

        total = (await db.execute(text(f"""
            SELECT COUNT(*) FROM brand_hsn_enrichment_log {where_clause}
        """), {k: v for k, v in params.items() if k not in ("limit", "offset")})).scalar() or 0

    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Audit log query failed: {exc}")

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": r["id"],
                "table_name": r["table_name"],
                "record_id": r.get("record_id"),
                "product_name": r.get("product_name"),
                "old_hsn": r.get("old_hsn"),
                "new_hsn": r.get("new_hsn"),
                "old_gst": r.get("old_gst"),
                "new_gst": r.get("new_gst"),
                "change_reason": r.get("change_reason"),
                "source_reference": r.get("source_reference"),
                "changed_at": str(r["changed_at"]) if r.get("changed_at") else None,
            }
            for r in rows
        ],
    }
