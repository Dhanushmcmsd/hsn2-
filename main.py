from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import select, String, Float, Integer, Text, Boolean, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pydantic import BaseModel, field_validator
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional
import os, json, re

# ── Config ────────────────────────────────────────────────────────────────────
DATABASE_URL  = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql+asyncpg://", 1)
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "change-me")
JWT_SECRET    = os.environ.get("JWT_SECRET", os.environ.get("SECRET_KEY", "change-me"))
ALGORITHM     = "HS256"
REDIS_URL     = os.environ.get("REDIS_URL", os.environ.get("UPSTASH_REDIS_URL", ""))

if not DATABASE_URL:
    import sys
    sys.exit("FATAL: DATABASE_URL env var is not set.")

if DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# ── DB setup ──────────────────────────────────────────────────────────────────
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    if "asyncpg" in DATABASE_URL else {},
)
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

class BatchQuery(BaseModel):
    queries: list[str]

    @field_validator("queries")
    @classmethod
    def check_limit(cls, v):
        if len(v) > 1000:
            raise ValueError("Maximum 1000 queries per request")
        return v

class SingleQuery(BaseModel):
    text: str

class HSNBatchResult(BaseModel):
    query: str
    hsn_code: Optional[str] = None
    description: Optional[str] = None
    gst_rate: Optional[float] = None
    confidence: float = 0.0
    confidence_label: str = "low"
    match_method: str = "none"
    alternatives: list[dict] = []
    error: Optional[str] = None

class BatchResponse(BaseModel):
    results: list[HSNBatchResult]
    total: int
    matched: int
    unmatched: int

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="HSN Classifier API", version="2.0.0")

ALLOWED_ORIGINS = [
    "https://hsn2.vercel.app",
    "https://hsn2-git-main-d3d.vercel.app",
    "https://hsn2-485zotyhz-d3d.vercel.app",
    "https://hsn2-git-main-krithu.vercel.app",
    "https://hsn2-krithu.vercel.app",
    "https://hsn-app-krithu.vercel.app",
    "http://localhost:3000",
    "http://localhost:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT COUNT(*) FROM hsn_master"))
        hsn_count = result.scalar()
    except Exception:
        hsn_count = 0
    return {
        "status": "ok",
        "redis": "connected" if redis_client else "disabled",
        "hsn_records": hsn_count,
        "version": "2.0.0"
    }

# ── Auth routes ───────────────────────────────────────────────────────────────
@app.post("/auth/register", response_model=UserOut, status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(409, "Email already registered")
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

# ── HSN lookup routes ─────────────────────────────────────────────────────────
@app.get("/hsn/{code}", response_model=HSNRow)
async def get_by_code(code: str, db: AsyncSession = Depends(get_db)):
    cached = await cache_get(f"hsn:{code}")
    if cached:
        return cached
    result = await db.execute(select(HSNMaster).where(HSNMaster.hsn_code == code))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, f"HSN code {code!r} not found")
    data = HSNRow.model_validate(row).model_dump()
    await cache_set(f"hsn:{code}", data)
    return data

@app.get("/hsn", response_model=list[HSNRow])
async def search_hsn(
    q:        Optional[str]   = Query(None),
    rate:     Optional[float] = Query(None),
    category: Optional[str]   = Query(None),
    limit:    int             = Query(20, le=200),
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

# ── Single predict (compatible with app/ frontend) ────────────────────────────
@app.post("/predict")
async def predict_single(
    body: SingleQuery,
    authorization: str = Header(default=""),
    x_api_key: str = Header(default="", alias="x-api-key"),
    db: AsyncSession = Depends(get_db),
):
    """Single item prediction - compatible with the app/ frontend API calls."""
    # Auth: accept either JWT Bearer or X-API-Key
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            decode_token(token)
        except Exception:
            raise HTTPException(401, "Invalid token")
    elif x_api_key:
        if x_api_key not in (ADMIN_API_KEY, os.environ.get("API_KEY", "dev-api-key")):
            raise HTTPException(401, "Invalid API key")
    else:
        raise HTTPException(422, "Provide Authorization: Bearer <token> or X-API-Key")

    result = await _match_one(body.text, db)

    # Return in PredictResponse format compatible with frontend
    import uuid, time
    confidence_label = result.confidence_label
    return {
        "request_id": str(uuid.uuid4()),
        "input_text": body.text,
        "top_match": {
            "hsn_code": result.hsn_code or "9999",
            "description": result.description or "Not classified",
            "score": result.confidence,
            "method": result.match_method,
        },
        "alternatives": [
            {
                "hsn_code": a.get("hsn_code", ""),
                "description": a.get("description", ""),
                "score": a.get("confidence", 0),
                "method": "keyword",
            }
            for a in result.alternatives[:4]
        ],
        "confidence": result.confidence,
        "confidence_label": confidence_label,
        "needs_review": result.confidence < 0.55,
        "processing_time_ms": 0,
    }

# ── Admin upsert ──────────────────────────────────────────────────────────────
@app.post("/admin/hsn/upsert", response_model=HSNRow)
async def upsert_hsn(
    data: HSNRow,
    x_api_key: str = Header(..., alias="x-api-key"),
    db: AsyncSession = Depends(get_db),
):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(403, "Invalid API key")
    stmt = pg_insert(HSNMaster).values(**data.model_dump())
    stmt = stmt.on_conflict_do_update(
        index_elements=["hsn_code"],
        set_={k: v for k, v in data.model_dump().items() if k != "hsn_code"},
    )
    await db.execute(stmt)
    await db.commit()
    await cache_delete(f"hsn:{data.hsn_code}")
    return data

@app.post("/admin/hsn/bulk-upsert")
async def bulk_upsert_hsn(
    records: list[HSNRow],
    x_api_key: str = Header(..., alias="x-api-key"),
    db: AsyncSession = Depends(get_db),
):
    """Bulk insert/update HSN records. Used to seed the database."""
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(403, "Invalid API key")
    if len(records) > 5000:
        raise HTTPException(400, "Max 5000 records per request")

    inserted = 0
    for data in records:
        stmt = pg_insert(HSNMaster).values(**data.model_dump())
        stmt = stmt.on_conflict_do_update(
            index_elements=["hsn_code"],
            set_={k: v for k, v in data.model_dump().items() if k != "hsn_code"},
        )
        await db.execute(stmt)
        inserted += 1

    await db.commit()
    return {"status": "ok", "inserted_or_updated": inserted}

@app.get("/admin/hsn/count")
async def hsn_count(
    x_api_key: str = Header(..., alias="x-api-key"),
    db: AsyncSession = Depends(get_db),
):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(403, "Invalid API key")
    result = await db.execute(text("SELECT COUNT(*) FROM hsn_master"))
    return {"count": result.scalar()}

# ── Batch endpoint ────────────────────────────────────────────────────────────
@app.post("/hsn/batch", response_model=BatchResponse)
async def batch_predict(
    body: BatchQuery,
    authorization: str = Header(default=""),
    x_api_key: str = Header(default="", alias="x-api-key"),
    db: AsyncSession = Depends(get_db),
):
    """Batch classify up to 1000 product descriptions into HSN codes."""
    # Flexible auth
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        email = decode_token(token)
        res = await db.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(401, "User not found or inactive")
    elif x_api_key:
        valid_keys = {ADMIN_API_KEY, os.environ.get("API_KEY", "dev-api-key")}
        if x_api_key not in valid_keys:
            raise HTTPException(401, "Invalid API key")
    else:
        raise HTTPException(401, "Authentication required")

    queries = [q.strip() for q in body.queries if q.strip()]

    results: list[HSNBatchResult] = []
    for query in queries:
        try:
            row = await _match_one(query, db)
            results.append(row)
        except Exception as e:
            results.append(HSNBatchResult(query=query, error=str(e)))

    matched = sum(1 for r in results if r.hsn_code)
    return BatchResponse(
        results=results,
        total=len(results),
        matched=matched,
        unmatched=len(results) - matched,
    )

# ── Core matching logic ───────────────────────────────────────────────────────

# Stopwords to ignore in matching
STOPWORDS = {
    'the','a','an','and','or','of','in','is','for','to','with','on','at',
    'by','from','are','was','be','as','it','its','this','that','per','ml',
    'gm','kg','ltr','litre','liter','gram','mg','unit','pack','piece','nos',
    'no','pcs','set','box','bottle','pouch','sachet','can','tin','jar','tube',
    'strip','tablet','capsule','pkt','packet','roll','sheet','size','new','free',
    'buy','get','pure','natural','original','brand','best','premium','super',
    '100','200','250','300','400','500','1000','50','25',
}

def tokenize(text: str) -> list[str]:
    """Extract meaningful tokens from product description."""
    text = text.lower()
    # Remove common quantity patterns like 200ml, 100g, 1kg
    text = re.sub(r'\b\d+\s*(ml|g|gm|kg|l|ltr|mg|oz|lb|pc|pcs|nos)\b', ' ', text)
    # Remove standalone numbers
    text = re.sub(r'\b\d+\b', ' ', text)
    tokens = re.findall(r'[a-z]{2,}', text)
    return [t for t in tokens if t not in STOPWORDS and len(t) >= 2]

async def _match_one(query: str, db: AsyncSession) -> HSNBatchResult:
    """
    Multi-pass HSN matching:
    1. Exact HSN code match (if numeric input)
    2. PostgreSQL full-text search (fast, uses GIN index)
    3. Token-based keyword overlap scoring
    """
    q_stripped = query.strip()

    # Pass 1: exact HSN code
    if re.match(r'^\d{4,8}$', q_stripped):
        res = await db.execute(
            select(HSNMaster).where(HSNMaster.hsn_code == q_stripped)
        )
        row = res.scalar_one_or_none()
        if row:
            return HSNBatchResult(
                query=query,
                hsn_code=row.hsn_code,
                description=row.description,
                gst_rate=row.gst_rate,
                confidence=1.0,
                confidence_label="high",
                match_method="exact_code",
            )

    # Pass 2: PostgreSQL full-text search using GIN index (very fast)
    tokens = tokenize(q_stripped)
    if tokens:
        # Build tsquery: try AND of all tokens, fall back to OR
        ts_and = " & ".join(tokens[:8])
        try:
            res = await db.execute(
                text("""
                    SELECT *, ts_rank(to_tsvector('english', description || ' ' || notes), query) as rank
                    FROM hsn_master, to_tsquery('english', :q) query
                    WHERE to_tsvector('english', description || ' ' || notes) @@ query
                    ORDER BY rank DESC
                    LIMIT 10
                """),
                {"q": ts_and}
            )
            rows_fts = res.fetchall()
            if not rows_fts:
                # Fall back to OR query
                ts_or = " | ".join(tokens[:8])
                res = await db.execute(
                    text("""
                        SELECT *, ts_rank(to_tsvector('english', description || ' ' || notes), query) as rank
                        FROM hsn_master, to_tsquery('english', :q) query
                        WHERE to_tsvector('english', description || ' ' || notes) @@ query
                        ORDER BY rank DESC
                        LIMIT 10
                    """),
                    {"q": ts_or}
                )
                rows_fts = res.fetchall()
        except Exception:
            rows_fts = []

        if rows_fts:
            # Score FTS results by token overlap
            best = None
            best_score = 0
            alts = []

            for r in rows_fts:
                desc_tokens = set(tokenize(r.description + " " + (r.notes or "")))
                query_tokens = set(tokens)
                if not desc_tokens or not query_tokens:
                    continue
                # Jaccard-like: intersection / union
                intersection = query_tokens & desc_tokens
                union = query_tokens | desc_tokens
                score = len(intersection) / len(union) if union else 0
                # Boost by FTS rank
                fts_boost = min(float(r.rank) * 2, 0.3)
                final_score = min(score + fts_boost, 1.0)

                entry = {
                    "hsn_code": r.hsn_code,
                    "description": r.description,
                    "gst_rate": r.gst_rate,
                    "confidence": round(final_score, 3),
                }
                if final_score > best_score:
                    if best:
                        alts.append(best)
                    best = entry
                    best_score = final_score
                else:
                    alts.append(entry)

            if best and best_score > 0.05:
                if best_score >= 0.65:
                    label = "high"
                elif best_score >= 0.35:
                    label = "medium"
                else:
                    label = "low"

                return HSNBatchResult(
                    query=query,
                    hsn_code=best["hsn_code"],
                    description=best["description"],
                    gst_rate=best["gst_rate"],
                    confidence=round(best_score, 3),
                    confidence_label=label,
                    match_method="fulltext",
                    alternatives=alts[:4],
                )

    # Pass 3: ILIKE keyword fallback for short/simple queries
    if tokens:
        candidates: dict[str, dict] = {}
        for token in tokens[:4]:
            if len(token) < 3:
                continue
            res = await db.execute(
                select(HSNMaster).where(
                    HSNMaster.description.ilike(f"%{token}%")
                ).limit(20)
            )
            for r in res.scalars().all():
                if r.hsn_code not in candidates:
                    candidates[r.hsn_code] = {"row": r, "hits": 0}
                candidates[r.hsn_code]["hits"] += 1

        if candidates:
            total_tokens = max(len(tokens), 1)
            scored = sorted(
                [(c["hits"] / total_tokens, c["row"]) for c in candidates.values()],
                key=lambda x: x[0],
                reverse=True,
            )
            top_score, top_row = scored[0]

            if top_score > 0.1:
                label = "high" if top_score >= 0.65 else ("medium" if top_score >= 0.35 else "low")
                alternatives = [
                    {"hsn_code": r.hsn_code, "description": r.description,
                     "gst_rate": r.gst_rate, "confidence": round(s, 3)}
                    for s, r in scored[1:4] if s > 0
                ]
                return HSNBatchResult(
                    query=query,
                    hsn_code=top_row.hsn_code,
                    description=top_row.description,
                    gst_rate=top_row.gst_rate,
                    confidence=round(top_score, 3),
                    confidence_label=label,
                    match_method="keyword",
                    alternatives=alternatives,
                )

    return HSNBatchResult(query=query, confidence=0.0, confidence_label="low", match_method="none")

# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Create GIN index for full-text search if it doesn't exist
        try:
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_hsn_description_gin
                ON hsn_master USING gin(to_tsvector('english', description || ' ' || notes))
            """))
        except Exception:
            pass
