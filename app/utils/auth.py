# app/utils/auth.py
from __future__ import annotations

import hashlib
import secrets

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"


def _const_api_key_eq(a: str, b: str) -> bool:
    """Constant-time comparison for API keys of arbitrary length."""
    if not a or not b:
        return False
    return secrets.compare_digest(
        hashlib.sha256(a.encode("utf-8")).digest(),
        hashlib.sha256(b.encode("utf-8")).digest(),
    )


async def require_api_key(request: Request) -> str:
    """Accept X-API-Key header OR a valid JWT Bearer token."""
    x_api_key = request.headers.get("X-API-Key")
    if x_api_key:
        if _const_api_key_eq(x_api_key, settings.API_KEY) or _const_api_key_eq(
            x_api_key, settings.ADMIN_API_KEY
        ):
            return x_api_key
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        )

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
        detail="Authentication failed",
    )


async def require_admin_key(request: Request) -> str:
    x_api_key = request.headers.get("X-API-Key")
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin key required")
    if not _const_api_key_eq(x_api_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin key required")
    return x_api_key
