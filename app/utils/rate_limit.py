import enum
import hashlib
import time

from fastapi import HTTPException, status
from sqlalchemy import select

from app.models.database import ApiKey, async_session
from app.utils.cache import get_redis


class RateLimitTier(enum.Enum):
    FREE = 100
    STANDARD = 1000
    ENTERPRISE = 10000


async def _resolve_tier(api_key: str) -> str:
    if api_key.startswith("jwt:"):
        return "standard"
    try:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        async with async_session() as db:
            row = (
                await db.execute(
                    select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
                )
            ).scalars().first()
            if row and row.tier:
                return str(row.tier).lower()
    except Exception:
        pass
    return "standard"


def _limit_for_tier(tier_name: str) -> int:
    tier_name = (tier_name or "standard").lower()
    if tier_name == "free":
        return RateLimitTier.FREE.value
    if tier_name == "enterprise":
        return RateLimitTier.ENTERPRISE.value
    return RateLimitTier.STANDARD.value


async def check_rate_limit(api_key: str, endpoint: str = "predict"):
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
        if count > limit_per_hour:
            retry_after = max(0, 3600 - (int(time.time()) % 3600))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "retry_after_seconds": retry_after,
                    "tier": tier_name,
                    "contact": "support@yourdomain.com",
                },
            )
    except HTTPException:
        raise
    except Exception:
        pass
