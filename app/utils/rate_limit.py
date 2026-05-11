import hashlib
import time
from enum import Enum

from fastapi import HTTPException, status
from sqlalchemy import select

from app.models.database import ApiKey, async_session
from app.utils.cache import get_redis


class RateLimitTier(str, Enum):
    FREE = "free"
    STANDARD = "standard"
    ENTERPRISE = "enterprise"


TIER_LIMITS = {
    RateLimitTier.FREE: 100,
    RateLimitTier.STANDARD: 1000,
    RateLimitTier.ENTERPRISE: 10000,
}


async def _resolve_tier(api_key: str) -> str:
    if api_key.startswith("jwt:"):
        return RateLimitTier.STANDARD.value
    api_key_prefix = api_key[:8]
    r = await get_redis()
    cache_key = f"apikey_tier:{api_key_prefix}"
    if r:
        try:
            cached = await r.get(cache_key)
            if cached:
                return str(cached).lower()
        except Exception:
            pass
    try:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        async with async_session() as db:
            row = (
                await db.execute(
                    select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
                )
            ).scalars().first()
            if row and row.tier:
                tier_value = str(row.tier).lower()
                if r:
                    try:
                        await r.setex(cache_key, 300, tier_value)
                    except Exception:
                        pass
                return tier_value
    except Exception:
        pass
    return RateLimitTier.STANDARD.value


def _limit_for_tier(tier_name: str) -> int:
    tier_name = (tier_name or RateLimitTier.STANDARD.value).lower()
    try:
        return TIER_LIMITS[RateLimitTier(tier_name)]
    except Exception:
        return TIER_LIMITS[RateLimitTier.STANDARD]


async def check_rate_limit(api_key: str, endpoint: str = "predict") -> dict | None:
    r = await get_redis()
    if not r:
        return

    tier_name = await _resolve_tier(api_key)
    limit_per_hour = _limit_for_tier(tier_name)
    window = int(time.time()) // 3600
    api_key_prefix = api_key[:8]
    key = f"ratelimit:{api_key_prefix}:{endpoint}:{window}"
    try:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 3700)
        remaining = max(0, limit_per_hour - count)
        reset_ts = ((int(time.time()) // 3600) + 1) * 3600
        headers = {
            "X-RateLimit-Limit": str(limit_per_hour),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_ts),
        }
        if count > limit_per_hour:
            retry_after = max(0, 3600 - (int(time.time()) % 3600))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after)},
                detail={
                    "error": "rate_limit_exceeded",
                    "retry_after_seconds": retry_after,
                    "tier": tier_name,
                    "contact": "support@hsnclassifier.in",
                },
            )
        return headers
    except HTTPException:
        raise
    except Exception:
        pass
