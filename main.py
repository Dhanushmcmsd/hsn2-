from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import select, String, Float, Integer, Text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pydantic import BaseModel
from typing import Optional
import os, json, redis.asyncio as aioredis

# ── Config ────────────────────────────────────────────────────────────────────
DATABASE_URL   = os.environ["DATABASE_URL"]          # from Render env vars
REDIS_URL      = os.environ["UPSTASH_REDIS_URL"]     # from Render env vars
ADMIN_API_KEY  = os.environ.get("ADMIN_API_KEY", "change-me")
JWT_SECRET     = os.environ["JWT_SECRET"]

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

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# ── Redis ─────────────────────────────────────────────────────────────────────
redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

async def cache_get(key: str):
    val = await redis_client.get(key)
    return json.loads(val) if val else None

async def cache_set(key: str, data, ttl: int = 86400):
    await redis_client.setex(key, ttl, json.dumps(data, default=str))

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="HSN Classifier API")

# CORS — all Vercel preview URLs + production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hsn2.vercel.app",
        "https://hsn2-git-main-d3d.vercel.app",
        "https://hsn2-485zotyhz-d3d.vercel.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Cron-job.org pings this every 10 min to prevent Render cold start."""
    return {"status": "ok"}

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
    await redis_client.delete(f"hsn:{data.hsn_code}")
    return data

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
