# app/utils/auth.py
from __future__ import annotations
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from app.config import settings

ALGORITHM = "HS256"


async def require_api_key(request: Request) -> str:
    """Accept X-API-Key header OR a valid JWT Bearer token."""
    x_api_key = request.headers.get("X-API-Key")
    if x_api_key:
        if x_api_key in (settings.API_KEY, settings.ADMIN_API_KEY):
            return x_api_key
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
            if payload.get("type") == "access" and payload.get("sub"):
                return f"jwt:{payload['sub']}"
        except JWTError:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Provide a valid X-API-Key header or Authorization: Bearer <token>",
    )


async def require_admin_key(request: Request) -> str:
    x_api_key = request.headers.get("X-API-Key")
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin key required")
    if x_api_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin key required")
    if x_api_key == settings.API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User key rejected for admin routes")
    return x_api_key
