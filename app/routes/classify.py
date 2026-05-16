"""GST Classification API — multi-tier fallback pipeline (no external AI).

Endpoints added by this module (additive, do NOT overlap with existing routes):
  POST /api/v1/classify          — classify a single product query (6-tier + multi-layer fallback)
  POST /api/v1/classify/batch    — classify up to 50 products at once (same 6-tier pipeline)
  GET  /api/v1/classify/cache    — look up a cached result without triggering re-classification
  GET  /api/v1/classify/pending  — list pending manual review items (admin only)

Existing routes (/search/*, /predict, /hsn) are completely unaffected.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.models.database import async_session, get_db
from app.services import gst_classifier
from app.services.audit_logger import log_classify_event
from app.utils.auth import require_api_key, require_admin_key

router = APIRouter(prefix="/api/v1/classify", tags=["GST Classification"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ClassifyRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Product name or description")
    bypass_cache: bool = Field(False, description="Skip cache and re-classify")
    enable_ai: bool = Field(
        False,
        description="Deprecated. Ignored (external AI classifier was removed).",
    )


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
    # Additive layer metadata (backward-compatible)
    confidence_score: Optional[int] = None
    matched_layer: Optional[str] = None
    matched_source_table: Optional[str] = None
    code_type: Optional[str] = None
    tax_semantics: Optional[str] = None
    cess_rate: Optional[float] = None
    effective_total_tax: Optional[float] = None
    review_required: Optional[bool] = None
    rate_conflict: bool = False
    trust_level: Optional[str] = None
    alternates: list[dict] = Field(default_factory=list)


# FIX: Pydantic v2 dropped min_items/max_items on Field for lists.
# Use Annotated with list constraints instead.
class BatchClassifyRequest(BaseModel):
    queries: Annotated[list[str], Field(min_length=1, max_length=50)] = Field(
        ..., description="Up to 50 product queries"
    )
    bypass_cache: bool = False
    enable_ai: bool = Field(False, description="Deprecated. Ignored.")


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
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(require_api_key),
) -> ClassifyResult:
    """
    Classify a product description through cache, DB matchers, then manual review if needed.

    **Tier 0** — DB cache (instant)
    **Tier 1** — Exact brand match (brand_aliases, CBIC verified)
    **Tier 2** — Exact product match (verified_products)
    **Tier 3** — Curated ``hsn_master`` (promoted goods codes)
    **Tier 4** — Keyword/category map
    **Tier 5** — Tariff fallback → fuzzy → multi-layer search
    **Tier 6** — Manual review queue (low confidence or no match)

    SAC services resolve via ``service_master`` (never padded to 8-digit HSN).
    """
    started = time.perf_counter()
    result = await gst_classifier.classify(
        db,
        body.query,
        bypass_cache=body.bypass_cache,
    )
    response = ClassifyResult(**result)
    request_id = getattr(request.state, "request_id", "")
    client_ip = request.client.host if request.client else ""
    await log_classify_event(
        request_id=request_id,
        api_key=api_key,
        client_ip=client_ip,
        product_name=body.query,
        hsn_code=response.hsn_code,
        gst_rate=response.gst_rate,
        confidence_score=response.confidence_score or response.confidence,
        layer_matched=response.matched_layer or response.source,
        response_time_ms=(time.perf_counter() - started) * 1000,
    )
    return response


@router.post("/batch", response_model=BatchClassifyResponse, summary="Batch classify up to 50 products")
async def classify_batch(
    body: BatchClassifyRequest,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
) -> BatchClassifyResponse:
    """Classify multiple products in parallel (max 50 per request)."""
    import time
    started = time.perf_counter()

    async def _classify_one(q: str):
        async with async_session() as session:
            return await gst_classifier.classify(
                session, q, bypass_cache=body.bypass_cache,
            )

    raw_results = await asyncio.gather(
        *[_classify_one(q) for q in body.queries],
        return_exceptions=True,
    )

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
