from __future__ import annotations
import json
from typing import Any, Optional
import structlog
from app.config import settings

log = structlog.get_logger()
_redis = None


async def init_cache():
    global _redis
    try:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await _redis.ping()
        log.info("cache.connected")
    except Exception as e:
        log.warning("cache.unavailable", error=str(e))
        _redis = None


async def get_redis():
    return _redis


async def get_cache(key: str) -> Optional[Any]:
    if not _redis:
        return None
    try:
        val = await _redis.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


async def set_cache(key: str, value: Any, ttl: int = None) -> None:
    if not _redis:
        return
    try:
        await _redis.setex(key, ttl or settings.CACHE_TTL, json.dumps(value))
    except Exception as e:
        log.warning("cache.set_error", error=str(e))
