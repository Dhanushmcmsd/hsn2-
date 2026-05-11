# app/utils/auth.py
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from app.config import settings
from app.models.database import ApiKey, Branch, User, UserRole, async_session, get_db
from sqlalchemy.ext.asyncio import AsyncSession

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(user: User, org_id: str | None, expires_delta: timedelta) -> str:
    payload = {
        "sub": str(user.id),
        "type": "access",
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
        "branch_id": str(user.branch_id) if user.branch_id else None,
        "org_id": org_id,
        "exp": datetime.utcnow() + expires_delta,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        token_type = payload.get("type")
        if user_id is None or token_type != "access":
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exc
    user.jwt_role = payload.get("role")
    user.jwt_branch_id = payload.get("branch_id")
    user.jwt_org_id = payload.get("org_id")
    return user


def require_role(*roles: UserRole):
    async def _inner(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        current_role = current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role)
        allowed = {r.value if isinstance(r, UserRole) else str(r) for r in roles}
        if current_role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return current_user
    return _inner


async def require_api_key(request: Request) -> str:
    """Accept X-API-Key header OR a valid JWT Bearer token."""
    x_api_key = request.headers.get("X-API-Key")
    if x_api_key:
        if x_api_key in (settings.API_KEY, settings.ADMIN_API_KEY):
            return x_api_key
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        async with async_session() as db:
            row = (await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True))).scalars().first()
            if row:
                if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail={
                            "error": "api_key_expired",
                            "message": "Please rotate your API key via the admin console",
                        },
                    )
                async def _touch_last_used(key_id: int) -> None:
                    try:
                        async with async_session() as s2:
                            key = (await s2.execute(select(ApiKey).where(ApiKey.id == key_id))).scalars().first()
                            if key:
                                key.last_used_at = datetime.now(timezone.utc)
                                await s2.commit()
                    except Exception:
                        return
                asyncio.create_task(_touch_last_used(row.id))
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
