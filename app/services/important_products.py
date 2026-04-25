from __future__ import annotations
import json
import os
from pathlib import Path
import structlog
from typing import List, Dict, Any

log = structlog.get_logger()

# PROTOTYPE: This feature is not integrated into the main prediction flow.
IMPORTANT_PRODUCTS_FILE = Path("data/csv.json")
_important_products: List[Dict[str, Any]] = []


def load_important_products() -> List[Dict[str, Any]]:
    """Load important products from csv.json file."""
    global _important_products
    if not IMPORTANT_PRODUCTS_FILE.exists():
        log.warning("important_products.file_missing", path=str(IMPORTANT_PRODUCTS_FILE))
        return []
    
    try:
        with open(IMPORTANT_PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            _important_products = json.load(f)
        log.info("important_products.loaded", count=len(_important_products))
        return _important_products
    except Exception as e:
        log.error("important_products.load_error", error=str(e))
        return []


def get_important_products() -> List[Dict[str, Any]]:
    """Get all important products, loading if necessary."""
    if not _important_products:
        load_important_products()
    return _important_products


def save_important_products(products: List[Dict[str, Any]]) -> bool:
    """Save important products back to file."""
    try:
        with open(IMPORTANT_PRODUCTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(products, f, indent=2, ensure_ascii=False)
        _important_products[:] = products
        log.info("important_products.saved", count=len(products))
        return True
    except Exception as e:
        log.error("important_products.save_error", error=str(e))
        return False


def update_product_hsn(product_index: int, hsn_code: str, confidence: float) -> bool:
    """Update HSN code for a specific product if confidence is high."""
    products = get_important_products()
    if 0 <= product_index < len(products):
        products[product_index]["hsn_code"] = hsn_code
        products[product_index]["confidence"] = confidence
        products[product_index]["status"] = "auto_updated" if confidence >= 0.8 else "review_recommended"
        return save_important_products(products)
    return False
