from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import select, String, Float, Integer, Text, Boolean
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional
import os, json

# ── Config ────────────────────────────────────────────────────────────────────
DATABASE_URL  = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql+asyncpg://", 1)
REDIS_URL     = os.environ.get("UPSTASH_REDIS_URL", "")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "change-me")
JWT_SECRET    = os.environ.get("JWT_SECRET", "change-me")
ALGORITHM     = "HS256"

if not DATABASE_URL:
    import sys
    sys.exit("FATAL: DATABASE_URL env var is not set. Add it in Render → Environment.")

if DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# ── DB setup ──────────────────────────────────────────────────────────────────
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class HSNMaster(Base):
    __tablename__ = "hsn_master"
    id:          Mapped[int]   = mapped_column(Integer, primary_key=True)
    hsn_code:    Mapped[str]   = mapped_column(String(20), unique=True, index=True)
    description: Mapped[str]   = mapped_column(Text)
    gst_rate:    Mapped[float] = mapped_column(Float)
    chapter:     Mapped[int]   = mapped_column(Integer)
    category:    Mapped[str]   = mapped_column(String(100))
    notes:       Mapped[str]   = mapped_column(Text, default="")

class User(Base):
    __tablename__ = "users"
    id:               Mapped[int]  = mapped_column(Integer, primary_key=True)
    email:            Mapped[str]  = mapped_column(String(255), unique=True, index=True)
    full_name:        Mapped[str]  = mapped_column(String(255), default="")
    hashed_password:  Mapped[str]  = mapped_column(String(255))
    is_active:        Mapped[bool] = mapped_column(Boolean, default=True)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# ── Redis (optional) ──────────────────────────────────────────────────────────
redis_client = None
if REDIS_URL:
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        redis_client = None

async def cache_get(key: str):
    if not redis_client:
        return None
    try:
        val = await redis_client.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None

async def cache_set(key: str, data, ttl: int = 86400):
    if not redis_client:
        return
    try:
        await redis_client.setex(key, ttl, json.dumps(data, default=str))
    except Exception:
        pass

async def cache_delete(key: str):
    if not redis_client:
        return
    try:
        await redis_client.delete(key)
    except Exception:
        pass

# ── Auth helpers ──────────────────────────────────────────────────────────────
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def make_token(sub: str, minutes: int) -> str:
    exp = datetime.utcnow() + timedelta(minutes=minutes)
    return jwt.encode({"sub": sub, "exp": exp}, JWT_SECRET, algorithm=ALGORITHM)

def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")

# ── Pydantic schemas ──────────────────────────────────────────────────────────
class HSNRow(BaseModel):
    hsn_code:    str
    description: str
    gst_rate:    float
    chapter:     int
    category:    str
    notes:       str = ""
    class Config:
        from_attributes = True

class RegisterIn(BaseModel):
    email:     str
    password:  str
    full_name: str = ""

class UserOut(BaseModel):
    id: int; email: str; full_name: str; is_active: bool
    class Config: from_attributes = True

class TokenResponse(BaseModel):
    access_token: str; refresh_token: str; token_type: str = "bearer"

class RefreshIn(BaseModel):
    refresh_token: str

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="HSN Classifier API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hsn2.vercel.app",
        "https://hsn2-git-main-d3d.vercel.app",
        "https://hsn2-485zotyhz-d3d.vercel.app",
        "https://hsn2-git-main-krithu.vercel.app",
        "https://hsn2-krithu.vercel.app",
        "https://hsn-app-krithu.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "redis": "connected" if redis_client else "disabled"}

# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/auth/register", response_model=UserOut)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    user = User(
        email=body.email,
        full_name=body.full_name,
        hashed_password=pwd_ctx.hash(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

@app.post("/auth/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()
    if not user or not pwd_ctx.verify(form.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    return TokenResponse(
        access_token=make_token(user.email, 60),
        refresh_token=make_token(user.email, 60 * 24 * 7),
    )

@app.post("/auth/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshIn):
    email = decode_token(body.refresh_token)
    return TokenResponse(
        access_token=make_token(email, 60),
        refresh_token=make_token(email, 60 * 24 * 7),
    )

@app.get("/auth/me", response_model=UserOut)
async def me(authorization: str = Header(...), db: AsyncSession = Depends(get_db)):
    token = authorization.removeprefix("Bearer ")
    email = decode_token(token)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    return user

# ── HSN routes ────────────────────────────────────────────────────────────────

@app.get("/hsn/{code}", response_model=HSNRow)
async def get_by_code(code: str, db: AsyncSession = Depends(get_db)):
    cached = await cache_get(f"hsn:{code}")
    if cached:
        return cached
    result = await db.execute(select(HSNMaster).where(HSNMaster.hsn_code == code))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, f"HSN code {code!r} not found")
    data = HSNRow.from_orm(row).dict()
    await cache_set(f"hsn:{code}", data)
    return data

@app.get("/hsn", response_model=list[HSNRow])
async def search(
    q:        Optional[str]   = Query(None, description="Keyword in description"),
    rate:     Optional[float] = Query(None, description="GST rate: 0/5/12/18/28"),
    category: Optional[str]   = Query(None),
    limit:    int             = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(HSNMaster)
    if q:
        stmt = stmt.where(HSNMaster.description.ilike(f"%{q}%"))
    if rate is not None:
        stmt = stmt.where(HSNMaster.gst_rate == rate)
    if category:
        stmt = stmt.where(HSNMaster.category.ilike(f"%{category}%"))
    result = await db.execute(stmt.limit(limit))
    return result.scalars().all()

@app.post("/admin/hsn/upsert", response_model=HSNRow)
async def upsert_hsn(
    data: HSNRow,
    x_api_key: str = Header(..., alias="x-api-key"),
    db: AsyncSession = Depends(get_db),
):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(403, "Invalid API key")
    stmt = pg_insert(HSNMaster).values(**data.dict())
    stmt = stmt.on_conflict_do_update(
        index_elements=["hsn_code"],
        set_={k: v for k, v in data.dict().items() if k != "hsn_code"},
    )
    await db.execute(stmt)
    await db.commit()
    await cache_delete(f"hsn:{data.hsn_code}")
    return data

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
