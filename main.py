from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import select, String, Float, Integer, Text, Boolean, DateTime, Numeric, Date, text
from pydantic import BaseModel, field_validator
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional
import os, json, re, uuid

# ── Config ───────────────────────────────────────────────────────────────────
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
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "ssl": "require",
    } if "asyncpg" in DATABASE_URL else {},
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class HSNCode(Base):
    """Maps to hsn_codes table in Neon PostgreSQL."""
    __tablename__ = "hsn_codes"

    id:                  Mapped[str]            = mapped_column(String(36), primary_key=True)
    hsn_code:            Mapped[str]            = mapped_column(String(8), index=True)
    hsn_chapter:         Mapped[Optional[str]]  = mapped_column(String(2))
    hsn_heading:         Mapped[Optional[str]]  = mapped_column(String(4))
    hsn_subheading:      Mapped[Optional[str]]  = mapped_column(String(6))
    description:         Mapped[str]            = mapped_column(Text)
    cbic_description:    Mapped[Optional[str]]  = mapped_column(Text)
    parent_heading_desc: Mapped[Optional[str]] = mapped_column(Text)
    unit_of_measure:     Mapped[Optional[str]]  = mapped_column(String(20))
    customs_duty:        Mapped[Optional[str]]  = mapped_column(String(20))
    gst_rate:            Mapped[float]          = mapped_column(Numeric(5, 2), default=0.0)
    cess:                Mapped[Optional[str]]  = mapped_column(String(50))
    schedule:            Mapped[Optional[str]]  = mapped_column(String(150))
    category:            Mapped[Optional[str]]  = mapped_column(String(100))
    cbic_notification:   Mapped[Optional[str]]  = mapped_column(String(150))
    effective_from:      Mapped[Optional[str]]  = mapped_column(Date)
    effective_to:        Mapped[Optional[str]]  = mapped_column(Date)
    is_active:           Mapped[bool]           = mapped_column(Boolean, default=True)
    created_at:          Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at:          Mapped[Optional[datetime]] = mapped_column(DateTime)


class User(Base):
    __tablename__ = "users"
    id:              Mapped[int]  = mapped_column(Integer, primary_key=True)
    email:           Mapped[str]  = mapped_column(String(255), unique=True, index=True)
    full_name:       Mapped[str]  = mapped_column(String(255), default="")
    hashed_password: Mapped[str]  = mapped_column(String(255))
    is_active:       Mapped[bool] = mapped_column(Boolean, default=True)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ── Redis (optional) ─────────────────────────────────────────────────────────
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
    category:    Optional[str] = None

    class Config:
        from_attributes = True


class RegisterIn(BaseModel):
    email:     str
    password:  str
    full_name: str = ""


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


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


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="HSN Classifier API", version="2.2.0")

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


# ── Health ───────────────────────────────────────────────────────────────────
@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT COUNT(*) FROM hsn_codes WHERE is_active = TRUE"))
        hsn_count = result.scalar()
    except Exception:
        hsn_count = 0

    try:
        search_result = await db.execute(text("SELECT COUNT(*) FROM hsn_search"))
        search_count = search_result.scalar()
    except Exception:
        search_count = 0

    return {
        "status": "ok",
        "redis": "connected" if redis_client else "disabled",
        "hsn_records": hsn_count,
        "hsn_search_records": search_count,
        "version": "2.2.0",
    }


# ── Auth routes ─────────────────────────────────────────────────────────────
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
    result = await db.execute(
        text("""
            SELECT hsn_code, description, gst_rate, category
            FROM hsn_codes
            WHERE hsn_code = :code AND is_active = TRUE
            LIMIT 1
        """),
        {"code": code},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, f"HSN code {code!r} not found")
    data = {
        "hsn_code": row.hsn_code,
        "description": row.description,
        "gst_rate": float(row.gst_rate or 0),
        "category": row.category,
    }
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
    stmt = "SELECT hsn_code, description, gst_rate, category FROM hsn_codes WHERE is_active = TRUE"
    params: dict = {}
    if q:
        stmt += " AND description ILIKE :q"
        params["q"] = f"%{q}%"
    if rate is not None:
        stmt += " AND gst_rate = :rate"
        params["rate"] = rate
    if category:
        stmt += " AND category ILIKE :cat"
        params["cat"] = f"%{category}%"
    stmt += f" LIMIT {int(limit)}"
    result = await db.execute(text(stmt), params)
    return [
        {
            "hsn_code": r.hsn_code,
            "description": r.description,
            "gst_rate": float(r.gst_rate or 0),
            "category": r.category,
        }
        for r in result.fetchall()
    ]


# ── FMCG Abbreviation Expansion endpoint ─────────────────────────────────────
@app.post("/expand-abbreviations")
async def expand_abbreviations_endpoint(body: SingleQuery):
    """Expand FMCG abbreviations in the input text."""
    expanded = expand_fmcg_abbreviations(body.text)
    return {
        "original": body.text,
        "expanded": expanded,
        "changed": expanded != body.text,
    }


# ── Single predict ────────────────────────────────────────────────────────────
@app.post("/predict")
async def predict_single(
    body: SingleQuery,
    authorization: str = Header(default=""),
    x_api_key: str = Header(default="", alias="x-api-key"),
    db: AsyncSession = Depends(get_db),
):
    """Single item prediction — compatible with the app/ frontend."""
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            decode_token(token)
        except Exception:
            raise HTTPException(401, "Invalid token")
    elif x_api_key:
        valid_keys = {ADMIN_API_KEY, os.environ.get("API_KEY", "dev-api-key")}
        if x_api_key not in valid_keys:
            raise HTTPException(401, "Invalid API key")
    else:
        raise HTTPException(422, "Provide Authorization: Bearer <token> or X-API-Key header")

    result = await _match_one(body.text, db)

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
                "method": "search",
            }
            for a in result.alternatives[:4]
        ],
        "confidence": result.confidence,
        "confidence_label": result.confidence_label,
        "needs_review": result.confidence < 0.55,
        "processing_time_ms": 0,
    }


# ── Batch endpoint ────────────────────────────────────────────────────────────
@app.post("/hsn/batch", response_model=BatchResponse)
async def batch_predict(
    body: BatchQuery,
    authorization: str = Header(default=""),
    x_api_key: str = Header(default="", alias="x-api-key"),
    db: AsyncSession = Depends(get_db),
):
    """Batch classify up to 1000 product descriptions into HSN codes."""
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


# ═══════════════════════════════════════════════════════════════════════════════
# MATCHING LOGIC — v2.2.0
# Fixes applied:
#   1. Placeholder chapter boost: Ch 33, 34, 39, 96
#   2. BRANDS: vkc, cb, cbindal, kitchen, treasure added
#   3. Ch 64 footwear routing (sandal/chappal/slipper/shoe/hawai)
#   4. TR → "kitchen treasure" expansion (masala brand prefix)
#   5. FTGR → fenugreek, methi synonyms, Ch 09 routing
#   6. SS → stainless steel, Ch 73 routing
#   7. CB brand kept as opaque (no chapter assumed)
# ═══════════════════════════════════════════════════════════════════════════════

STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'in', 'is', 'for', 'to', 'with', 'on', 'at',
    'by', 'from', 'are', 'was', 'be', 'as', 'it', 'its', 'this', 'that', 'per', 'ml',
    'gm', 'kg', 'ltr', 'litre', 'liter', 'gram', 'mg', 'unit', 'pack', 'piece', 'nos',
    'no', 'pcs', 'set', 'box', 'bottle', 'pouch', 'sachet', 'can', 'tin', 'jar', 'tube',
    'strip', 'tablet', 'capsule', 'pkt', 'packet', 'roll', 'sheet', 'size', 'new', 'free',
    'buy', 'get', 'pure', 'natural', 'original', 'brand', 'best', 'premium', 'super',
    '100', '200', '250', '300', '400', '500', '1000', '50', '25',
    'mixed', 'colour', 'assorted', 'round', 'square', 'rectangular', 'oval', 'flat',
    'long', 'short', 'small', 'large', 'medium', 'big', 'tiny', 'huge', 'thick', 'thin',
    'wide', 'narrow', 'high', 'low', 'deep', 'shallow', 'full', 'empty', 'half', 'quarter',
    'whole', 'part', 'piece', 'slice', 'chunk', 'bit', 'portion', 'section', 'segment',
    'various', 'different', 'multiple', 'several', 'many', 'few', 'single', 'double', 'triple',
    'regular', 'extra', 'special', 'standard', 'basic', 'advanced', 'simple', 'complex',
    'normal', 'unusual', 'usual', 'common', 'rare', 'unique', 'ordinary', 'general', 'specific',
    'particular', 'certain', 'diverse',
    # size/grade markers common in Kerala trade invoices
    'no1', 'no2', 'grade', 'quality', 'type', 'variety', 'model', 'make',
    'cover', 'wrapper', 'wt', 'weight', 'net', 'gross',
}

# BRANDS: names that carry no chapter signal — strip before routing.
# FIX #2: vkc (footwear), cb (multi-category Kerala brand), kitchen/treasure added.
# NOTE: "tr" kept OUT of BRANDS — abbreviation expander handles it first.
BRANDS = {
    'patanjali', 'nestle', 'amul', 'tata', 'godrej', 'dettol', 'lifebuoy', 'colgate',
    'pepsodent', 'nivea', 'garnier', 'loreal', 'sony', 'samsung', 'apple',
    'lg', 'whirlpool', 'philips', 'nike', 'adidas', 'puma', 'reebok',
    'bajaj', 'marico', 'unilever', 'parle', 'sunrise', 'mogambo', 'mtr',
    'majestic', 'micromax', 'boat', 'mivi', 'britannia', 'honda', 'suzuki',
    # Kerala-specific brands (FIX #2 & #7)
    'vkc',       # VKC footwear — largest single brand in dataset (603 items)
    'cb',        # CB brand — multi-category, do NOT assume any chapter
    'cbindal',   # CB Indal variant
    'kitchen',   # "kitchen treasure" after TR expansion — brand word 1
    'treasure',  # "kitchen treasure" after TR expansion — brand word 2
}

SYNONYMS = {
    'wash':      ['soap', 'cleanser'],
    'phone':     ['mobile', 'smartphone'],
    'tv':        ['television'],
    'fridge':    ['refrigerator'],
    'laptop':    ['notebook'],
    # FIX #3: footwear synonyms for Ch 64 routing
    'chappal':   ['sandal', 'footwear', 'slipper'],
    'slipper':   ['sandal', 'footwear', 'chappal'],
    'sandal':    ['footwear', 'slipper', 'chappal'],
    'shoe':      ['footwear'],
    'hawai':     ['slipper', 'footwear'],
    # FIX #6: stainless steel
    'stainless': ['steel', 'metal'],
    # FIX #5: fenugreek / methi
    'fenugreek': ['methi', 'spice'],
    'methi':     ['fenugreek', 'spice'],
}

# FIX #1–#6: Expanded abbreviation table
FMCG_ABBREVIATIONS = {
    # v2.2.0 additions
    'tr':     'kitchen treasure',  # FIX #4: Kitchen Treasure masala brand prefix
    'ftgr':   'fenugreek',         # FIX #5: fenugreek / methi seeds
    'ss':     'stainless steel',   # FIX #6: SS PLATE, SS OVAL etc.
    'ss.':    'stainless steel',
    # Cleaning
    'btrm':   'bathroom',
    'clnr':   'cleaner',
    'dtgnt':  'detergent',
    # Food
    'cookis': 'cookie',
    'cashw':  'cashew',
    'jasmne': 'jasmine',
    'choc':   'chocolate',
    'van':    'vanilla',
    'strbry': 'strawberry',
    'rasbry': 'raspberry',
    'bluebry':'blueberry',
    'blkbry': 'blackberry',
    'pstr':   'pasta',
    'nood':   'noodle',
    'sauc':   'sauce',
    'ketch':  'ketchup',
    'must':   'mustard',
    'mayo':   'mayonnaise',
    'yog':    'yogurt',
    'chee':   'cheese',
    'butr':   'butter',
    'marg':   'margarine',
    # Personal care
    'shamp':  'shampoo',
    'cond':   'conditioner',
    'det':    'detergent',
    'fab':    'fabric',
    'soft':   'softener',
    'dish':   'dishwasher',
    'liq':    'liquid',
    'powd':   'powder',
    'tab':    'tablet',
    'cap':    'capsule',
    'syrup':  'syrup',
    # Condiments
    'vin':    'vinegar',
    'sug':    'sugar',
    'pick':   'pickle',
    'sach':   'sachet',
    'cann':   'canned',
    'bott':   'bottled',
    'cart':   'carton',
    # Trade
    'prem':   'premium',
    'org':    'organic',
    'nat':    'natural',
    'imp':    'imported',
    'loc':    'local',
    'dom':    'domestic',
    'froz':   'frozen',
}


def expand_fmcg_abbreviations(text: str) -> str:
    """
    Expand FMCG / trade abbreviations.
    Pattern-based rules run first (handles word-boundary cases),
    then token-by-token dictionary lookup.
    """
    # FIX #6: SS prefix → stainless steel
    text = re.sub(r'\bSS\b', 'stainless steel', text, flags=re.IGNORECASE)
    # FIX #5: FTGR → fenugreek
    text = re.sub(r'\bFTGR\b', 'fenugreek', text, flags=re.IGNORECASE)
    # FIX #4: TR. or TR (word boundary) → kitchen treasure
    text = re.sub(r'\bTR\.\s*', 'kitchen treasure ', text, flags=re.IGNORECASE)
    text = re.sub(r'\bTR\b', 'kitchen treasure', text, flags=re.IGNORECASE)

    words = text.split()
    expanded = []
    for word in words:
        lower = word.lower().rstrip('.')
        expanded.append(FMCG_ABBREVIATIONS.get(lower, word))
    return ' '.join(expanded)


def tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r'\b\d+\s*(ml|g|gm|kg|l|ltr|mg|oz|lb|pc|pcs|nos)\b', ' ', text)
    text = re.sub(r'\b\d+\b', ' ', text)
    tokens = re.findall(r'[a-z]{2,}', text)
    return [t for t in tokens if t not in STOPWORDS and t not in BRANDS and len(t) >= 2]


def expand_tokens(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        expanded.extend(SYNONYMS.get(token, []))
    return expanded


# ── Domain prefix hints (HSN chapter → keyword mapping) ──────────────────────
# FIX #3: Added Ch 64 footwear routing for VKC and similar brands
DOMAIN_PREFIXES: dict[str, list[str]] = {
    'cosmetics':    ['33'],
    'makeup':       ['33'],
    'skincare':     ['33'],
    'skin':         ['33'],
    'soap':         ['34'],
    'cleanser':     ['34'],
    'shampoo':      ['33'],
    'bath':         ['33', '34'],
    'phone':        ['85'],
    'mobile':       ['85'],
    'smartphone':   ['85'],
    'television':   ['85'],
    'tv':           ['85'],
    'camera':       ['85'],
    'computer':     ['84'],
    'notebook':     ['84'],
    'laptop':       ['84'],
    'refrigerator': ['84'],
    'fridge':       ['84'],
    'washing':      ['84'],
    'footwear':     ['64'],
    'sandal':       ['64'],
    'slipper':      ['64'],
    'chappal':      ['64'],
    'shoe':         ['64'],
    'boot':         ['64'],
    'hawai':        ['64'],
    'stainless':    ['73'],
    'steel':        ['73'],
    'fenugreek':    ['09'],
    'methi':        ['09'],
    'spice':        ['09'],
    'masala':       ['09', '21'],
    'chilli':       ['09'],
    'turmeric':     ['09'],
    'pepper':       ['09'],
    'cardamom':     ['09'],
    'garment':      ['61', '62'],
    'clothing':     ['61', '62', '63'],
    'tshirt':       ['61'],
    'confectionery': ['19'],
    'biscuit':      ['19'],
    'cookie':       ['19'],
    'bread':        ['19'],
    'drink':        ['22'],
    'beverage':     ['22'],
    'water':        ['22'],
    'mineral':      ['22'],
    'juice':        ['22'],
}

# Category rules (priority-ordered; first match wins).
# IMPORTANT Order:
#   - computer/laptop MUST come before notebook (laptop synonym expands to notebook)
#   - biscuit/cookie added for Ch 19
#   - water/drink added for Ch 22
#   - shirt/garment added for Ch 61-63
CATEGORY_RULES = [
    {'keywords': ['tooth', 'paste', 'toothpaste'],                                       'chapters': ['33'],           'description': 'toothpaste → ch 33'},
    {'keywords': ['computer', 'laptop'],                                                 'chapters': ['84'],           'description': 'computers → ch 84'},
    {'keywords': ['note', 'book', 'notebook'],                                           'chapters': ['48'],           'description': 'notebook → ch 48'},
    {'keywords': ['puja'],                                                               'chapters': ['33'],           'description': 'puja items → ch 33 (agarbatti etc.)'},
    {'keywords': ['footwear', 'sandal', 'slipper', 'chappal', 'shoe', 'boot', 'hawai'], 'chapters': ['64'],           'description': 'footwear → ch 64'},
    {'keywords': ['stainless', 'steel'],                                                 'chapters': ['73'],           'description': 'stainless steel → ch 73'},
    {'keywords': ['cleaning', 'cleaner', 'detergent'],                                   'chapters': ['34'],           'description': 'cleaning products → ch 34'},
    {'keywords': ['cosmetic', 'makeup', 'skincare'],                                     'chapters': ['33'],           'description': 'cosmetics → ch 33'},
    {'keywords': ['soap', 'shampoo'],                                                    'chapters': ['33', '34'],     'description': 'soap/shampoo → ch 33/34'},
    {'keywords': ['phone', 'mobile', 'smartphone'],                                      'chapters': ['85'],           'description': 'phones → ch 85'},
    {'keywords': ['tv', 'television'],                                                   'chapters': ['85'],           'description': 'TV → ch 85'},
    {'keywords': ['fridge', 'refrigerator'],                                             'chapters': ['84'],           'description': 'refrigerators → ch 84'},
    {'keywords': ['masala', 'spice', 'fenugreek', 'methi', 'chilli', 'turmeric', 'pepper', 'cardamom'],
                                                                                         'chapters': ['09', '21'],     'description': 'spices/masala → ch 09/21'},
    {'keywords': ['oil'],                                                                'chapters': ['15'],           'description': 'edible oil → ch 15'},
    {'keywords': ['biscuit', 'cookie', 'confectionery', 'bakery', 'bread', 'cake', 'cracker'], 'chapters': ['19'], 'description': 'bakery/confectionery → ch 19'},
    {'keywords': ['water', 'drink', 'beverage', 'juice', 'soda', 'mineral'],             'chapters': ['22'],           'description': 'beverages/water → ch 22'},
    {'keywords': ['food', 'beverage', 'drink'],                                          'chapters': ['04', '19', '20', '21', '22'], 'description': 'food/beverages'},
    {'keywords': ['clothing', 'garment', 'fabric', 'shirt', 'tshirt', 'trouser', 'pant', 'saree', 'kurta'],
                                                                                         'chapters': ['61', '62', '63'], 'description': 'clothing → ch 61-63'},
    {'keywords': ['furniture'],                                                          'chapters': ['94'],           'description': 'furniture → ch 94'},
    {'keywords': ['toy', 'game'],                                                        'chapters': ['95'],           'description': 'toys/games → ch 95'},
    {'keywords': ['plastic', 'polythene', 'polymer', 'pvc', 'polyethylene'],             'chapters': ['39'],           'description': 'plastics → ch 39'},
    {'keywords': ['brush', 'broom', 'comb', 'button', 'zip', 'zipper', 'pen', 'pencil'], 'chapters': ['96'],           'description': 'misc manufactured → ch 96'},
]


def detect_category_restrictions(tokens: list[str]) -> list[str]:
    """Return HSN chapter prefixes to restrict search to, based on token keywords.

    NOTE: Intentionally uses raw tokens only — NOT synonym-expanded — so that
    the laptop→notebook synonym expansion cannot accidentally trigger the
    notebook (ch 48) rule when the query is about computers.
    """
    for rule in CATEGORY_RULES:
        if any(keyword in tokens for keyword in rule['keywords']):
            return rule['chapters']
    return []


def build_hsn_prefix_clause(tokens: list[str]) -> tuple[str, dict]:
    """Build a SQL WHERE clause fragment restricting to relevant HSN chapters."""
    expanded_tokens = set(tokens)
    for token in tokens:
        expanded_tokens.update(SYNONYMS.get(token, []))

    category_chapters = detect_category_restrictions(list(expanded_tokens))
    if category_chapters:
        prefixes = category_chapters
    else:
        prefixes = []
        for token in expanded_tokens:
            prefixes.extend(DOMAIN_PREFIXES.get(token, []))

    prefixes = sorted(set(prefixes))
    if not prefixes:
        return "", {}

    clause_parts = []
    params: dict[str, str] = {}
    for idx, prefix in enumerate(prefixes):
        param_name = f"prefix_{idx}"
        clause_parts.append(f"h.hsn_code LIKE :{param_name}")
        params[param_name] = f"{prefix}%"
    return " AND (" + " OR ".join(clause_parts) + ")", params


def build_tsquery_terms(tokens: list[str]) -> list[str]:
    """Build tsquery terms with synonym expansion."""
    query_terms: list[str] = []
    for token in tokens:
        variants = [token] + SYNONYMS.get(token, [])
        if len(variants) > 1:
            query_terms.append("(" + " | ".join(variants) + ")")
        else:
            query_terms.append(token)
    return query_terms


def compute_weighted_jaccard(tokens: list[str], desc_tokens: set[str]) -> float:
    """Jaccard similarity with synonym and repeated-token weighting, capped at 1.0."""
    query_weights: dict[str, int] = {}
    for token in tokens:
        query_weights[token] = max(query_weights.get(token, 0), 2)
        for synonym in SYNONYMS.get(token, []):
            query_weights[synonym] = max(query_weights.get(synonym, 0), 1)

    intersection_weight = sum(
        weight for term, weight in query_weights.items() if term in desc_tokens
    )
    union_weight = sum(query_weights.values()) + len(desc_tokens) - intersection_weight
    if union_weight <= 0:
        return 0.0
    return min(intersection_weight / union_weight, 1.0)


PLACEHOLDER_BOOST_CHAPTERS = {'33', '34', '39', '96'}


def _apply_placeholder_boost(hsn_code: str, score: float) -> float:
    """Add a small boost for high-priority placeholder chapters."""
    chapter = hsn_code[:2] if len(hsn_code) >= 2 else ''
    if chapter in PLACEHOLDER_BOOST_CHAPTERS:
        return min(score * 1.05, 1.0)
    return score


async def _match_one(query: str, db: AsyncSession) -> HSNBatchResult:
    """
    Multi-pass HSN matching against Neon DB tables:
      hsn_codes  — master data with gst_rate, is_active, etc.
      hsn_search — FTS search_vector (GIN), trigram on normalized_description

    Pass 0: FMCG abbreviation expansion (TR, FTGR, SS etc.)
    Pass 1: Exact HSN code match (if numeric input)
    Pass 2: Full-text search via hsn_search.search_vector (GIN index)
    Pass 3: Trigram similarity on hsn_search.normalized_description
    Pass 4: ILIKE keyword fallback on hsn_codes.description
    """
    q_stripped = query.strip()

    if re.match(r'^\d{4,8}$', q_stripped):
        res = await db.execute(
            text("""
                SELECT h.hsn_code, h.description, h.gst_rate, h.category
                FROM hsn_codes h
                WHERE h.hsn_code = :code AND h.is_active = TRUE
                LIMIT 1
            """),
            {"code": q_stripped},
        )
        row = res.fetchone()
        if row:
            return HSNBatchResult(
                query=query,
                hsn_code=row.hsn_code,
                description=row.description,
                gst_rate=float(row.gst_rate or 0),
                confidence=1.0,
                confidence_label="high",
                match_method="exact_code",
            )

    q_expanded = expand_fmcg_abbreviations(q_stripped)
    tokens = tokenize(q_expanded)
    if not tokens:
        return HSNBatchResult(query=query, match_method="none")

    domain_clause, domain_params = build_hsn_prefix_clause(tokens)

    rows_fts = []
    try:
        ts_query_terms = build_tsquery_terms(tokens)
        ts_and = " & ".join(ts_query_terms[:8])
        query_params = {"q": ts_and, **domain_params}
        res = await db.execute(
            text("""
                SELECT
                    h.hsn_code,
                    h.description,
                    h.gst_rate,
                    h.category,
                    ts_rank(s.search_vector, query) AS rank
                FROM hsn_search s
                JOIN hsn_codes h ON h.hsn_code = s.hsn_code
                CROSS JOIN to_tsquery('english', :q) query
                WHERE s.search_vector @@ query
                  AND h.is_active = TRUE""" + domain_clause + """
                ORDER BY rank DESC
                LIMIT 15
            """),
            query_params,
        )
        rows_fts = res.fetchall()
    except Exception:
        rows_fts = []

    if not rows_fts and len(tokens) > 1:
        try:
            ts_or = " | ".join(ts_query_terms[:8])
            query_params = {"q": ts_or, **domain_params}
            res = await db.execute(
                text("""
                    SELECT
                        h.hsn_code,
                        h.description,
                        h.gst_rate,
                        h.category,
                        ts_rank(s.search_vector, query) AS rank
                    FROM hsn_search s
                    JOIN hsn_codes h ON h.hsn_code = s.hsn_code
                    CROSS JOIN to_tsquery('english', :q) query
                    WHERE s.search_vector @@ query
                      AND h.is_active = TRUE""" + domain_clause + """
                    ORDER BY rank DESC
                    LIMIT 15
                """),
                query_params,
            )
            rows_fts = res.fetchall()
        except Exception:
            rows_fts = []

    if rows_fts:
        best = None
        best_score = 0.0
        alts = []

        for r in rows_fts:
            desc_tokens = set(tokenize(r.description))
            if not desc_tokens:
                continue
            jaccard = compute_weighted_jaccard(tokens, desc_tokens)
            fts_score = min(float(r.rank) * 2.5, 0.4)
            raw_score = min(jaccard * 0.6 + fts_score, 1.0)
            final_score = _apply_placeholder_boost(r.hsn_code, raw_score)

            entry = {
                "hsn_code": r.hsn_code,
                "description": r.description,
                "gst_rate": float(r.gst_rate or 0),
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
            label = "high" if best_score >= 0.65 else ("medium" if best_score >= 0.35 else "low")
            return HSNBatchResult(
                query=query,
                hsn_code=best["hsn_code"],
                description=best["description"],
                gst_rate=best["gst_rate"],
                confidence=round(best_score, 3),
                confidence_label=label,
                match_method="fulltext_fts",
                alternatives=alts[:4],
            )

    try:
        trgm_query = " ".join(tokens[:6])
        res = await db.execute(
            text("""
                SELECT
                    h.hsn_code,
                    h.description,
                    h.gst_rate,
                    h.category,
                    similarity(s.normalized_description, :q) AS sim
                FROM hsn_search s
                JOIN hsn_codes h ON h.hsn_code = s.hsn_code
                WHERE s.normalized_description % :q
                  AND h.is_active = TRUE""" + domain_clause + """
                ORDER BY sim DESC
                LIMIT 10
            """),
            {"q": trgm_query, **domain_params},
        )
        rows_trgm = res.fetchall()
    except Exception:
        rows_trgm = []

    if rows_trgm:
        best = rows_trgm[0]
        sim_score = _apply_placeholder_boost(best.hsn_code, float(best.sim))
        alts = [
            {
                "hsn_code": r.hsn_code,
                "description": r.description,
                "gst_rate": float(r.gst_rate or 0),
                "confidence": round(_apply_placeholder_boost(r.hsn_code, float(r.sim)), 3),
            }
            for r in rows_trgm[1:4]
        ]
        if sim_score > 0.15:
            label = "high" if sim_score >= 0.60 else ("medium" if sim_score >= 0.30 else "low")
            return HSNBatchResult(
                query=query,
                hsn_code=best.hsn_code,
                description=best.description,
                gst_rate=float(best.gst_rate or 0),
                confidence=round(sim_score, 3),
                confidence_label=label,
                match_method="trigram",
                alternatives=alts,
            )

    candidates: dict[str, dict] = {}
    for token in tokens[:4]:
        if len(token) < 3:
            continue
        res = await db.execute(
            text("""
                SELECT hsn_code, description, gst_rate, category
                FROM hsn_codes
                WHERE description ILIKE :pat AND is_active = TRUE""" + domain_clause + """
                LIMIT 20
            """),
            {"pat": f"%{token}%", **domain_params},
        )
        for r in res.fetchall():
            if r.hsn_code not in candidates:
                candidates[r.hsn_code] = {
                    "hsn_code": r.hsn_code,
                    "description": r.description,
                    "gst_rate": float(r.gst_rate or 0),
                    "hits": 0,
                }
            candidates[r.hsn_code]["hits"] += 1

    if candidates:
        total_tokens = max(len(tokens), 1)
        scored = sorted(
            [
                (_apply_placeholder_boost(c["hsn_code"], c["hits"] / total_tokens), c)
                for c in candidates.values()
            ],
            key=lambda x: x[0],
            reverse=True,
        )
        top_score, top_c = scored[0]
        if top_score > 0.1:
            label = "high" if top_score >= 0.65 else ("medium" if top_score >= 0.35 else "low")
            alts = [
                {
                    "hsn_code": c["hsn_code"],
                    "description": c["description"],
                    "gst_rate": c["gst_rate"],
                    "confidence": round(s, 3),
                }
                for s, c in scored[1:4]
                if s > 0
            ]
            return HSNBatchResult(
                query=query,
                hsn_code=top_c["hsn_code"],
                description=top_c["description"],
                gst_rate=top_c["gst_rate"],
                confidence=round(top_score, 3),
                confidence_label=label,
                match_method="keyword_ilike",
                alternatives=alts,
            )

    return HSNBatchResult(query=query, match_method="none")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    """
    Create only the users table if missing.
    DO NOT touch hsn_codes / hsn_search — they already exist in Neon
    with the correct schema, indexes, and ~10,957 records.
    """
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id              SERIAL PRIMARY KEY,
                email           VARCHAR(255) NOT NULL UNIQUE,
                full_name       VARCHAR(255) NOT NULL DEFAULT '',
                hashed_password VARCHAR(255) NOT NULL,
                is_active       BOOLEAN NOT NULL DEFAULT TRUE
            )
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)
        """))
