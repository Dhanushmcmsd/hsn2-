from fastapi import Header, HTTPException, status
from app.config import settings


async def require_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    if x_api_key not in (settings.API_KEY, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return x_api_key


async def require_admin_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    if x_api_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin key required")
    if x_api_key == settings.API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User key rejected for admin routes")
    return x_api_key
