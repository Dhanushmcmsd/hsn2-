from fastapi import HTTPException, status
from app.utils.cache import get_redis
from app.config import settings
import time


async def check_rate_limit(api_key: str):
    r = await get_redis()
    if not r:
        return
    window = int(time.time()) // 60
    key = f"ratelimit:{hash(api_key)}:{window}"
    try:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 120)
        if count > settings.RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {settings.RATE_LIMIT_PER_MINUTE} req/min",
            )
    except HTTPException:
        raise
    except Exception:
        pass
