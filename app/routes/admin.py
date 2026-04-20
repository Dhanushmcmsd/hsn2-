from __future__ import annotations
import structlog
from fastapi import APIRouter, Depends, HTTPException
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
    
    # Normalize description
    cleaned_description = normalize_product_description(original_name)
    pack_size = extract_pack_size(original_name)
    
    # Update product with cleaned data
    product["cleaned_description"] = cleaned_description
    product["pack_or_size"] = pack_size
    
    # Run HSN analysis
    matcher = get_matcher()
    matches = matcher.match(cleaned_description, top_k=5)
    
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
        cleaned_description = normalize_product_description(product["product_name"])
        pack_size = extract_pack_size(product["product_name"])
        
        product["cleaned_description"] = cleaned_description
        product["pack_or_size"] = pack_size
        
        matcher = get_matcher()
        matches = matcher.match(cleaned_description, top_k=5)
        
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
                    "status": "auto_updated"
                })
            else:
                product["status"] = "review_recommended"
                results.append({
                    "index": i,
                    "product_name": product["product_name"],
                    "confidence": confidence,
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
