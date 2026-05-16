"""Health check endpoint — also exposes cache stats for observability."""
from __future__ import annotations

from fastapi import APIRouter, Request
from app.services.in_memory_cache import lru_stats

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request):
    ready = getattr(request.app.state, "ready", False)
    cache_size = len(getattr(request.app.state, "product_name_cache", []))
    return {
        "status": "ok" if ready else "starting",
        "ready": ready,
        "product_name_cache_size": cache_size,
        "lru_cache": lru_stats(),
    }
