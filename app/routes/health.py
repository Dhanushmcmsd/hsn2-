from __future__ import annotations
import structlog
from fastapi import APIRouter
from sqlalchemy import text

from app.models.database import async_session
from app.utils.cache import get_redis
from app.services.dataset import get_dataset_version

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
