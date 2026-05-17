"""Health check endpoints for uptime probes and deploy dashboards."""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.models.database import async_session
from app.services.in_memory_cache import lru_stats
from app.utils.cache import get_redis

router = APIRouter(tags=["health"])

_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def _faiss_health() -> dict:
    try:
        from app.services.faiss_service import get_faiss_service

        svc = get_faiss_service()
        return {
            "ready": svc.ready,
            "loading": svc.loading,
            "failed": svc.failed,
            "load_time_ms": svc.load_time_ms,
            "index_size_bytes": svc.index_size_bytes,
        }
    except Exception:
        return {
            "ready": False,
            "loading": False,
            "failed": True,
            "load_time_ms": None,
            "index_size_bytes": None,
        }


def _basic_health_payload(request: Request) -> dict:
    ready = getattr(request.app.state, "ready", False)
    cache_size = len(getattr(request.app.state, "product_name_cache", []))
    return {
        "status": "ok" if ready else "starting",
        "ready": ready,
        "product_name_cache_size": cache_size,
        "lru_cache": lru_stats(),
        "faiss": _faiss_health(),
    }


@router.get("/health")
async def health_check(request: Request):
    return _basic_health_payload(request)


@router.get("/health/detailed")
async def health_detailed(request: Request):
    """Extended health payload (version + dependency checks) for monitoring."""
    payload = _basic_health_payload(request)
    payload["version"] = getattr(request.app, "version", None) or "1.0.0"
    payload["embedding_model"] = _EMBEDDING_MODEL
    payload["db"] = "ok"
    payload["cache"] = "ok"
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        payload["db"] = "error"
        payload["status"] = "degraded"
    try:
        redis = await get_redis()
        if redis:
            await redis.ping()
        else:
            payload["cache"] = "unavailable"
    except Exception:
        payload["cache"] = "error"
        payload["status"] = "degraded"
    return payload
