from __future__ import annotations
from datetime import datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import Branch, User, UserRole, get_db

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7
ALGORITHM = "HS256"


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60


class RefreshRequest(BaseModel):
    refresh_token: str


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(data: dict, expires_delta: timedelta) -> str:
    payload = {**data, "exp": datetime.utcnow() + expires_delta}
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
    async def _inner(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        current_role = getattr(current_user, "role", UserRole.BRANCH_USER.value)
        allowed = {r.value if isinstance(r, UserRole) else str(r) for r in roles}
        if current_role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return current_user

    return _inner


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: UserRegister, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log.info("user.registered", email=body.email)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    org_id = None
    if user.branch_id:
        branch = (
            await db.execute(select(Branch).where(Branch.id == user.branch_id))
        ).scalar_one_or_none()
        if branch is not None:
            org_id = str(branch.organisation_id)
    access_token = create_token(
        {
            "sub": str(user.id),
            "type": "access",
            "role": getattr(user, "role", UserRole.BRANCH_USER.value),
            "branch_id": str(user.branch_id) if user.branch_id else None,
            "org_id": org_id,
        },
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_token(
        {"sub": str(user.id), "type": "refresh"},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    log.info("user.login", email=user.email)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = jwt.decode(body.refresh_token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise ValueError("wrong token type")
        user_id = int(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    org_id = None
    if user.branch_id:
        branch = (
            await db.execute(select(Branch).where(Branch.id == user.branch_id))
        ).scalar_one_or_none()
        if branch is not None:
            org_id = str(branch.organisation_id)
    access_token = create_token(
        {
            "sub": str(user.id),
            "type": "access",
            "role": getattr(user, "role", UserRole.BRANCH_USER.value),
            "branch_id": str(user.branch_id) if user.branch_id else None,
            "org_id": org_id,
        },
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    new_refresh = create_token({"sub": str(user.id), "type": "refresh"}, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
    return TokenResponse(access_token=access_token, refresh_token=new_refresh)


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user
