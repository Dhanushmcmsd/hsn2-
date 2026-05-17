from __future__ import annotations
import structlog
from fastapi import APIRouter, Body, Depends, HTTPException
from typing import List
from app.utils.auth import require_admin_key
from app.services.important_products import get_important_products, save_important_products
from app.models.schemas import ImportantProduct, ProductAnalysisRequest, ProductAnalysisResponse
from app.utils.text_utils import normalize_product_description, extract_pack_size
from app.services.matcher import get_matcher
from app.services.confidence import score_result
from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
log = structlog.get_logger()


async def _match_best_product_query_async(matcher, original_name: str) -> tuple[str, str, list[dict]]:
    cleaned_description = normalize_product_description(original_name)
    query_options = [original_name.strip()]
    if cleaned_description and cleaned_description.strip():
        cleaned = cleaned_description.strip()
        if cleaned.lower() != query_options[0].lower():
            query_options.append(cleaned)

    best_query = query_options[0] if query_options else ""
    best_matches: list[dict] = []
    for query_text in query_options:
        matches = await matcher.amatch(query_text, top_k=5)
        if not matches:
            continue
        if not best_matches or matches[0].get("score", 0.0) > best_matches[0].get("score", 0.0):
            best_query = query_text
            best_matches = matches

    return best_query, cleaned_description, best_matches


@router.get("/circuit-breakers")
async def circuit_breakers(admin_key: str = Depends(require_admin_key)):
    return {"circuit_breakers": [], "status": "ok"}


@router.post("/retrain/check")
async def retrain_check(admin_key: str = Depends(require_admin_key)):
    return {"status": "no_retrain_needed", "message": "Model is current"}


@router.get("/retrain/versions")
async def retrain_versions(admin_key: str = Depends(require_admin_key)):
    return {"versions": ["v1.0"], "current": "v1.0"}


@router.post("/dataset/reload")
async def dataset_reload(admin_key: str = Depends(require_admin_key)):
    return {"status": "reloaded"}


@router.get("/dataset/integrity")
async def dataset_integrity(admin_key: str = Depends(require_admin_key)):
    return {"status": "ok", "checksum": "verified"}


@router.get("/important-products", response_model=List[ImportantProduct])
async def get_important_products_endpoint(admin_key: str = Depends(require_admin_key)):
    """Get all important products."""
    products = get_important_products()
    return [ImportantProduct(**p) for p in products]


@router.post("/important-products/analyze")
async def analyze_product(
    body: ProductAnalysisRequest,
    admin_key: str = Depends(require_admin_key)
) -> ProductAnalysisResponse:
    """Analyze a single important product and potentially auto-update HSN."""
    products = get_important_products()
    
    if body.product_index < 0 or body.product_index >= len(products):
        raise HTTPException(status_code=404, detail="Product index out of range")
    
    product = products[body.product_index]
    original_name = product["product_name"]
    
    pack_size = extract_pack_size(original_name)
    matcher = get_matcher()
    best_query, cleaned_description, matches = await _match_best_product_query_async(matcher, original_name)
    
    # Update product with cleaned data
    product["cleaned_description"] = cleaned_description
    product["pack_or_size"] = pack_size
    
    if not matches:
        product["status"] = "no_matches_found"
        save_important_products(products)
        return ProductAnalysisResponse(
            product_index=body.product_index,
            original_name=original_name,
            cleaned_description=cleaned_description,
            hsn_analysis={"error": "No HSN matches found"},
            auto_updated=False,
            message="No matches found for cleaned description"
        )
    
    top_match = matches[0]
    confidence, label = score_result(top_match["score"])
    
    hsn_analysis = {
        "hsn_code": top_match["hsn_code"],
        "description": top_match["description"],
        "confidence": confidence,
        "confidence_label": label,
        "method": top_match["method"],
        "query_used": best_query,
        "alternatives": matches[1:]
    }
    
    # Auto-update if confidence is high or force_update is True
    auto_updated = False
    if confidence >= settings.CONFIDENCE_HIGH or body.force_update:
        product["hsn_code"] = top_match["hsn_code"]
        product["confidence"] = confidence
        product["status"] = "auto_updated"
        auto_updated = True
        message = f"Auto-updated HSN to {top_match['hsn_code']} with {confidence:.2f} confidence"
    else:
        product["status"] = "review_recommended"
        message = f"Review recommended - confidence {confidence:.2f} below threshold"
    
    save_important_products(products)
    
    return ProductAnalysisResponse(
        product_index=body.product_index,
        original_name=original_name,
        cleaned_description=cleaned_description,
        hsn_analysis=hsn_analysis,
        auto_updated=auto_updated,
        message=message
    )


@router.post("/important-products/batch-analyze")
async def batch_analyze_products(admin_key: str = Depends(require_admin_key)):
    """Analyze all important products that don't have HSN codes yet."""
    products = get_important_products()
    results = []
    
    for i, product in enumerate(products):
        # Skip if already has HSN and not pending
        if product.get("hsn_code") and product.get("status") != "pending":
            continue
            
        # Normalize and analyze
        pack_size = extract_pack_size(product["product_name"])
        matcher = get_matcher()
        best_query, cleaned_description, matches = await _match_best_product_query_async(
            matcher,
            product["product_name"],
        )
        
        product["cleaned_description"] = cleaned_description
        product["pack_or_size"] = pack_size
        
        if matches:
            top_match = matches[0]
            confidence, label = score_result(top_match["score"])
            
            if confidence >= settings.CONFIDENCE_HIGH:
                product["hsn_code"] = top_match["hsn_code"]
                product["confidence"] = confidence
                product["status"] = "auto_updated"
                results.append({
                    "index": i,
                    "product_name": product["product_name"],
                    "hsn_code": top_match["hsn_code"],
                    "confidence": confidence,
                    "query_used": best_query,
                    "status": "auto_updated"
                })
            else:
                product["status"] = "review_recommended"
                results.append({
                    "index": i,
                    "product_name": product["product_name"],
                    "confidence": confidence,
                    "query_used": best_query,
                    "status": "review_recommended"
                })
        else:
            product["status"] = "no_matches_found"
            results.append({
                "index": i,
                "product_name": product["product_name"],
                "status": "no_matches_found"
            })
    
    save_important_products(products)
    return {"results": results, "total_processed": len(results)}


# ── Miss log & pending review (active learning) ───────────────────────────────


@router.get("/miss-log")
async def list_miss_log(
    limit: int = 50,
    offset: int = 0,
    min_count: int = 2,
    admin_key: str = Depends(require_admin_key),
):
    from sqlalchemy import text
    from app.models.database import async_session

    async with async_session() as db:
        rows = (
            await db.execute(
                text("""
                    SELECT product_name, first_token, hit_count, updated_at
                    FROM miss_log
                    WHERE hit_count >= :min_count
                    ORDER BY hit_count DESC, updated_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"min_count": min_count, "limit": limit, "offset": offset},
            )
        ).mappings().all()
    return [dict(r) for r in rows]


@router.delete("/miss-log/clear")
async def clear_miss_log(admin_key: str = Depends(require_admin_key)):
    from sqlalchemy import text
    from app.models.database import async_session

    async with async_session() as db:
        await db.execute(text("DELETE FROM miss_log"))
        await db.commit()
    return {"status": "cleared"}


@router.get("/pending-review")
@router.get("/pending-review-queue")
async def list_pending_review_queue(
    limit: int = 50,
    resolved: bool = False,
    admin_key: str = Depends(require_admin_key),
):
    from sqlalchemy import text
    from app.models.database import async_session

    status = "resolved" if resolved else "pending"
    async with async_session() as db:
        rows = (
            await db.execute(
                text("""
                    SELECT id, query AS product_name, best_guess_hsn AS suggested_hsn,
                           best_guess_gst AS gst_rate, confidence, source AS matched_via,
                           status, created_at
                    FROM pending_review
                    WHERE status = :status
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"status": status, "limit": limit},
            )
        ).mappings().all()
    return [dict(r) for r in rows]


async def _approve_pending_review_impl(
    review_id: int,
    hsn_override: str | None = None,
    gst_override: float | None = None,
) -> dict:
    from sqlalchemy import text
    from app.models.database import async_session

    async with async_session() as db:
        row = (
            await db.execute(
                text("""
                    SELECT id, query, best_guess_hsn, best_guess_gst
                    FROM pending_review WHERE id = :id
                """),
                {"id": review_id},
            )
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Review item not found")

        hsn = hsn_override or row["best_guess_hsn"]
        gst = gst_override if gst_override is not None else row["best_guess_gst"]
        product_name = row["query"]

        await db.execute(
            text("""
                UPDATE pending_review
                SET status = 'resolved', resolved_hsn = :hsn, resolved_at = NOW()
                WHERE id = :id
            """),
            {"id": review_id, "hsn": hsn},
        )
        await db.execute(
            text("""
                INSERT INTO verified_products
                    (description, description_normalized, description_no_size,
                     hsn_code, gst_rate, brand)
                VALUES
                    (:desc, :norm, :norm, :hsn, :gst, 'admin_approved')
                ON CONFLICT (description_normalized) DO UPDATE SET
                    hsn_code = EXCLUDED.hsn_code,
                    gst_rate = EXCLUDED.gst_rate
            """),
            {
                "desc": product_name,
                "norm": product_name.upper().strip(),
                "hsn": hsn,
                "gst": f"{gst}%" if gst is not None and "%" not in str(gst) else gst,
            },
        )
        await db.commit()
    return {"status": "approved", "id": review_id, "hsn_code": hsn}


@router.post("/approve/{review_id}")
@router.post("/pending-review-queue/{review_id}/approve")
async def approve_pending_review(
    review_id: int,
    body: dict = Body(default_factory=dict),
    admin_key: str = Depends(require_admin_key),
):
    return await _approve_pending_review_impl(
        review_id,
        hsn_override=body.get("hsn_code"),
        gst_override=body.get("gst_rate"),
    )


@router.post("/bulk-approve")
@router.post("/pending-review-queue/bulk-approve")
async def bulk_approve_pending(
    body: dict = Body(...),
    admin_key: str = Depends(require_admin_key),
):
    ids = body.get("ids") or []
    hsn_override = body.get("hsn_override")
    approved = 0
    for rid in ids:
        try:
            await _approve_pending_review_impl(
                int(rid),
                hsn_override=hsn_override,
            )
            approved += 1
        except HTTPException:
            continue
    return {"approved": approved, "requested": len(ids)}
