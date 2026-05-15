"""GST Classification API — 6-tier fallback pipeline.

Endpoints added by this module (additive, do NOT overlap with existing routes):
  POST /api/v1/classify          — classify a single product query
  POST /api/v1/classify/batch    — classify up to 50 products at once
  GET  /api/v1/classify/cache    — look up a cached result without triggering re-classification
  GET  /api/v1/classify/pending  — list pending manual review items (admin only)

Existing routes (/search/*, /predict, /hsn) are completely unaffected.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.database import get_db
from app.services.gst_classifier import classify
from app.utils.auth import require_api_key, require_admin_key

router = APIRouter(prefix="/api/v1/classify", tags=["GST Classification"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ClassifyRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Product name or description")
    bypass_cache: bool = Field(False, description="Skip cache and re-classify")
    enable_ai: bool = Field(True, description="Allow AI (Claude) fallback if DB tiers miss")


class ClassifyResult(BaseModel):
    hsn_code: Optional[str]
    description: Optional[str]
    gst_rate: Optional[float]
    cess_applicable: bool
    confidence: int
    tier_used: int
    source: str
    verified: bool
    last_updated: Optional[str]
    elapsed_ms: float
    needs_manual_review: bool = False


class BatchClassifyRequest(BaseModel):
    queries: list[str] = Field(..., min_items=1, max_items=50, description="Up to 50 product queries")
    bypass_cache: bool = False
    enable_ai: bool = True


class BatchClassifyResponse(BaseModel):
    results: dict[str, ClassifyResult]
    total: int
    elapsed_ms: float


class CachedResult(BaseModel):
    query_normalized: str
    hsn_code: str
    description: Optional[str]
    gst_rate: Optional[float]
    confidence: Optional[int]
    tier_used: Optional[int]
    hit_count: int
    expires_at: Optional[str]


class PendingReviewItem(BaseModel):
    id: int
    query: str
    best_guess_hsn: Optional[str]
    best_guess_gst: Optional[float]
    confidence: Optional[float]
    status: str
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ClassifyResult, summary="Classify a product for GST/HSN")
async def classify_product(
    body: ClassifyRequest,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
) -> ClassifyResult:
    """
    Classify a product description through the 6-tier GST/HSN pipeline.

    **Tier 0** — DB cache (instant)
    **Tier 1** — Exact brand match (brand_aliases, CBIC verified)
    **Tier 2** — Exact product match (verified_products)
    **Tier 3** — Fuzzy match (pg_trgm)
    **Tier 4** — Keyword/category match
    **Tier 5** — AI classification (Claude)
    **Tier 6** — Manual review queue
    """
    result = await classify(
        db,
        body.query,
        bypass_cache=body.bypass_cache,
        enable_ai=body.enable_ai,
    )
    return ClassifyResult(**result)


@router.post("/batch", response_model=BatchClassifyResponse, summary="Batch classify up to 50 products")
async def classify_batch(
    body: BatchClassifyRequest,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
) -> BatchClassifyResponse:
    """Classify multiple products in parallel (max 50 per request)."""
    import time
    started = time.perf_counter()

    tasks = [
        classify(db, q, bypass_cache=body.bypass_cache, enable_ai=body.enable_ai)
        for q in body.queries
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results: dict[str, ClassifyResult] = {}
    for query, raw in zip(body.queries, raw_results):
        if isinstance(raw, Exception):
            results[query] = ClassifyResult(
                hsn_code=None,
                description=f"Error: {str(raw)[:80]}",
                gst_rate=None,
                cess_applicable=False,
                confidence=0,
                tier_used=6,
                source="error",
                verified=False,
                last_updated=None,
                elapsed_ms=0.0,
                needs_manual_review=True,
            )
        else:
            results[query] = ClassifyResult(**raw)

    elapsed_ms = (time.perf_counter() - started) * 1000
    return BatchClassifyResponse(results=results, total=len(results), elapsed_ms=round(elapsed_ms, 2))


@router.get("/cache", summary="Look up a cached classification result")
async def get_cached_result(
    q: str = Query(..., min_length=1, max_length=500, description="Product query to look up"),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
) -> dict:
    """Returns a cached result if available, without triggering a new classification."""
    q_norm = re.sub(r"\s+", " ", q.upper().strip())
    try:
        row = (await db.execute(
            text("""
                SELECT query_normalized, hsn_code, description, gst_rate,
                       cess_applicable, confidence, tier_used, source,
                       hit_count, expires_at, created_at
                FROM search_cache
                WHERE query_normalized = :q
                  AND (expires_at IS NULL OR expires_at > NOW())
                LIMIT 1
            """),
            {"q": q_norm},
        )).mappings().first()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cache lookup failed: {exc}")

    if not row:
        return {"found": False, "query_normalized": q_norm}

    return {
        "found": True,
        "query_normalized": row["query_normalized"],
        "hsn_code": row["hsn_code"],
        "description": row.get("description"),
        "gst_rate": float(row["gst_rate"]) if row.get("gst_rate") is not None else None,
        "confidence": row.get("confidence"),
        "tier_used": row.get("tier_used"),
        "source": row.get("source"),
        "hit_count": row.get("hit_count", 0),
        "expires_at": str(row["expires_at"]) if row.get("expires_at") else None,
    }


@router.get(
    "/pending",
    summary="List items pending manual GST review (admin only)",
)
async def list_pending_reviews(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_admin_key),
) -> dict:
    """Returns queries that Tiers 1-5 couldn't classify with sufficient confidence."""
    try:
        rows = (await db.execute(
            text("""
                SELECT id, query, best_guess_hsn, best_guess_gst, confidence,
                       tier_used, status, admin_notes, created_at
                FROM pending_review
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": limit, "offset": offset},
        )).mappings().all()

        total_row = (await db.execute(
            text("SELECT COUNT(*) FROM pending_review WHERE status = 'pending'")
        )).scalar()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB error: {exc}")

    return {
        "total": total_row or 0,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": r["id"],
                "query": r["query"],
                "best_guess_hsn": r["best_guess_hsn"],
                "best_guess_gst": float(r["best_guess_gst"]) if r.get("best_guess_gst") is not None else None,
                "confidence": float(r["confidence"]) if r.get("confidence") is not None else None,
                "tier_used": r.get("tier_used"),
                "status": r["status"],
                "admin_notes": r.get("admin_notes"),
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ],
    }


@router.post("/pending/{item_id}/resolve", summary="Resolve a pending review item (admin only)")
async def resolve_pending(
    item_id: int,
    resolved_hsn: str = Query(..., description="Correct HSN code"),
    admin_notes: Optional[str] = Query(None, description="Admin notes"),
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_admin_key),
) -> dict:
    """Mark a pending review item as resolved with the correct HSN code."""
    if not re.match(r"^\d{2,8}$", resolved_hsn.strip()):
        raise HTTPException(status_code=400, detail="Invalid HSN code format")

    try:
        await db.execute(
            text("""
                UPDATE pending_review
                SET status = 'resolved',
                    resolved_hsn = :hsn,
                    admin_notes = :notes,
                    resolved_at = NOW()
                WHERE id = :item_id
            """),
            {"hsn": resolved_hsn.strip(), "notes": admin_notes, "item_id": item_id},
        )
        await db.commit()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB error: {exc}")

    return {"success": True, "item_id": item_id, "resolved_hsn": resolved_hsn}
