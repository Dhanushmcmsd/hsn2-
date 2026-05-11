from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.models.database import async_session
from app.utils.cache import get_redis
from app.services.dataset import get_dataset_version
from app.services.gst_fetcher import REDIS_KEY

router = APIRouter(tags=["health"])
log = structlog.get_logger()


@router.get("/health")
async def health():
    status = {"status": "ok", "db": "ok", "cache": "ok", "dataset": get_dataset_version()}
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
    except Exception as e:
        status["db"] = f"error: {e}"
        status["status"] = "degraded"
    try:
        r = await get_redis()
        if r:
            await r.ping()
        else:
            status["cache"] = "unavailable"
    except Exception as e:
        status["cache"] = f"error: {e}"
        status["status"] = "degraded"
    return status


@router.get("/health/detailed")
async def health_detailed():
    basic = await health()
    basic["version"] = "1.0.0"
    basic["embedding_model"] = "all-MiniLM-L6-v2"
    return basic


@router.get("/health/cache")
async def health_cache(
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-Api-Key"),
):
    """
    Admin-only cache health endpoint.
    Returns Redis connectivity, GST cache presence, entry count, and remaining TTL.
    Requires X-Admin-Api-Key header matching the ADMIN_API_KEY environment variable.
    """
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key or x_admin_api_key != admin_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Api-Key")

    try:
        r = await get_redis()
        if r is None:
            raise ConnectionError("Redis client not initialised")
        await r.ping()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"redis_connected": False},
        )

    try:
        raw = await r.get(REDIS_KEY)
        ttl = await r.ttl(REDIS_KEY)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"redis_connected": False},
        )

    if raw is None:
        return {
            "redis_connected": True,
            "gst_cache_present": False,
            "gst_cache_entry_count": 0,
            "cache_ttl_seconds": 0,
        }

    import json
    try:
        data = json.loads(raw)
        entry_count = len(data) if isinstance(data, dict) else 0
    except Exception:
        entry_count = 0

    return {
        "redis_connected": True,
        "gst_cache_present": True,
        "gst_cache_entry_count": entry_count,
        "cache_ttl_seconds": max(ttl, 0),
    }
