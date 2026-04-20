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

    id:                  Mapped[str]           = mapped_column(String(36), primary_key=True)
    hsn_code:            Mapped[str]           = mapped_column(String(8), index=True)
    hsn_chapter:         Mapped[Optional[str]] = mapped_column(String(2))
    hsn_heading:         Mapped[Optional[str]] = mapped_column(String(4))
    hsn_subheading:      Mapped[Optional[str]] = mapped_column(String(6))
    description:         Mapped[str]           = mapped_column(Text)
    cbic_description:    Mapped[Optional[str]] = mapped_column(Text)
    parent_heading_desc: Mapped[Optional[str]] = mapped_column(Text)
    unit_of_measure:     Mapped[Optional[str]] = mapped_column(String(20))
    customs_duty:        Mapped[Optional[str]] = mapped_column(String(20))
    gst_rate:            Mapped[float]         = mapped_column(Numeric(5, 2), default=0.0)
    cess:                Mapped[Optional[str]] = mapped_column(String(50))
    schedule:            Mapped[Optional[str]] = mapped_column(String(150))
    category:            Mapped[Optional[str]] = mapped_column(String(100))
    cbic_notification:   Mapped[Optional[str]] = mapped_column(String(150))
    effective_from:      Mapped[Optional[str]] = mapped_column(Date)
    effective_to:        Mapped[Optional[str]] = mapped_column(Date)
    is_active:           Mapped[bool]          = mapped_column(Boolean, default=True)
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

# ── HSN code normalizer ───────────────────────────────────────────────────────
# FIX: Leading zero normalization — "8013220" → "08013220"
# Applies everywhere an hsn_code is returned to the client.
def normalize_hsn(code: str) -> str:
    """Zero-pad HSN codes to 8 digits. Handles '8471', '84710000', '08471000' etc."""
    if not code or not code.strip():
        return code
    stripped = code.strip()
    # Only normalize numeric codes
    if re.match(r'^\d+$', stripped):
        return str(int(stripped)).zfill(8)
    return stripped

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

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            text("SELECT COUNT(*) FROM hsn_codes WHERE is_active = TRUE")
        )
        hsn_count = result.scalar()
    except Exception:
        hsn_count = 0

    try:
        search_result = await db.execute(text("SELECT COUNT(*) FROM hsn_search"))
        search_count = search_result.scalar()
    except Exception:
        search_count = 0

    try:
        vp_result = await db.execute(text("SELECT COUNT(*) FROM verified_products"))
        vp_count = vp_result.scalar()
    except Exception:
        vp_count = 0

    return {
        "status": "ok",
        "redis": "connected" if redis_client else "disabled",
        "hsn_records": hsn_count,
        "hsn_search_records": search_count,
        "verified_products": vp_count,
        "version": "2.2.0",
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
    # FIX: normalize before cache lookup so "8471" and "00008471" hit same key
    normalized_code = normalize_hsn(code)
    cached = await cache_get(f"hsn:{normalized_code}")
    if cached:
        return cached
    result = await db.execute(
        text("""
            SELECT hsn_code, description, gst_rate, category
            FROM hsn_codes
            WHERE hsn_code = :code AND is_active = TRUE
            LIMIT 1
        """),
        {"code": normalized_code}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(404, f"HSN code {code!r} not found")
    data = {
        "hsn_code": normalize_hsn(row.hsn_code),
        "description": row.description,
        "gst_rate": float(row.gst_rate or 0),
        "category": row.category,
    }
    await cache_set(f"hsn:{normalized_code}", data)
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
            "hsn_code": normalize_hsn(r.hsn_code),   # FIX: normalize output
            "description": r.description,
            "gst_rate": float(r.gst_rate or 0),
            "category": r.category,
        }
        for r in result.fetchall()
    ]

# ── FMCG Abbreviation Expansion ───────────────────────────────────────────────
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
    """Single item prediction — compatible with the hsn-frontend."""
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

    # FIX: normalize HSN code before returning
    top_hsn = normalize_hsn(result.hsn_code) if result.hsn_code else "99999999"

    return {
        "request_id": str(uuid.uuid4()),
        "input_text": body.text,
        "top_match": {
            "hsn_code": top_hsn,
            "description": result.description or "Not classified",
            "score": result.confidence,
            "method": result.match_method,
        },
        "alternatives": [
            {
                "hsn_code": normalize_hsn(a.get("hsn_code", "")),  # FIX: normalize alts too
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

# ── Batch endpoint ─────────────────────────────────────────────────────────────
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
            # FIX: normalize HSN code in batch results
            if row.hsn_code:
                row.hsn_code = normalize_hsn(row.hsn_code)
            for alt in row.alternatives:
                if alt.get("hsn_code"):
                    alt["hsn_code"] = normalize_hsn(alt["hsn_code"])
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

# ── Core matching dictionaries ────────────────────────────────────────────────

STOPWORDS = {
    'the','a','an','and','or','of','in','is','for','to','with','on','at',
    'by','from','are','was','be','as','it','its','this','that','per','ml',
    'gm','kg','ltr','litre','liter','gram','mg','unit','pack','piece','nos',
    'no','pcs','set','box','bottle','pouch','sachet','can','tin','jar','tube',
    'strip','tablet','capsule','pkt','packet','roll','sheet','size','new','free',
    'buy','get','pure','natural','original','brand','best','premium','super',
    '100','200','250','300','400','500','1000','50','25',
    'mixed','colour','assorted','round','square','rectangular','oval','flat',
    'long','short','small','large','medium','big','tiny','huge','thick','thin',
    'wide','narrow','high','low','deep','shallow','full','empty','half','quarter',
    'whole','part','piece','slice','chunk','bit','portion','section','segment',
    'various','different','multiple','several','many','few','single','double','triple',
    'regular','extra','special','standard','basic','advanced','simple','complex',
    'normal','abnormal','usual','unusual','common','rare','unique','ordinary',
    'general','specific','particular','certain','various','diverse','wide','narrow',
}

# UPDATED: Full brand list from 13,864-product dataset
# NOTE: 'cb' is intentionally NOT in this set — CB is a local Kerala brand
# appearing across many categories; do NOT assume a chapter for it.
# NOTE: 'vkc' IS kept here so it is filtered in tokenize() but SYNONYMS maps
# 'vkc' → ['footwear', 'sandal'...] so the chapter routing still works correctly
# via build_hsn_prefix_clause → detect_category_restrictions.
BRANDS = {
    # Dataset-specific brands
    'vkc', 'cello', 'manak', 'lemam', 'apaar', 'gebi', 'nolta',
    'bees', 'polyset', 'nakoda', 'esquire', 'real1', 'brillar',
    'orgello', 'lazza', 'jaipet', 'sithas', 'skei', 'ustraa',
    'mercely', 'mercelyn', 'homwow', 'impex', 'firmer',
    'topclean', 'ksk', 'kvg', 'kshethra',
    'keli', 'muram', 'liya', 'heyday', 'cupid', 'alfa',
    'colombo', 'flair', 'camlin', 'classmate', 'navneet',
    'kangaro', 'bakers', 'chozen', 'grandmas',
    'diva', 'brahmins', 'eastern',
    # Common national brands
    'patanjali', 'nestle', 'amul', 'tata', 'godrej', 'dettol',
    'lifebuoy', 'colgate', 'pepsodent', 'nivea', 'garnier', 'loreal',
    'sony', 'samsung', 'apple', 'lg', 'whirlpool', 'philips',
    'nike', 'adidas', 'puma', 'reebok', 'bajaj', 'marico',
    'unilever', 'parle', 'britannia', 'honda', 'suzuki',
    'himalaya', 'dove', 'yardley', 'gillette', 'pampers',
    'huggies', 'johnson', 'dabur', 'emami', 'meril',
    'harpic', 'lizol', 'ariel', 'surf', 'rin', 'vim',
    'haldirams', 'bikano', 'bikaji', 'balaji', 'prataap',
    'maggi', 'knorr', 'kissan', 'sunfeast', 'horlicks',
    'bournvita', 'complan', 'pediasure', 'boost',
    'cadbury', 'milkybar', 'kitkat',
    'lays', 'kurkure', 'pringles',
    'pepsi', 'sprite', 'fanta', 'maaza',
    'tropicana', 'paperboat',
    'milkymist', 'heritage',
    'moov', 'volini', 'iodex', 'burnol',
    'fogg', 'axe', 'engage',
    'maybelline', 'lakme', 'revlon',
    'cinthol', 'liril', 'lux', 'pears',
    'head', 'pantene', 'sunsilk', 'tresemme',
    'odonil', 'odomos', 'mortein', 'baygon', 'hit',
    'fevicol', 'fevistick', 'fevikwik', 'pidilite',
    'nataraj', 'apsara', 'faber', 'staedtler',
    'orbit', 'mentos', 'alpenliebe',
    'indiagate', 'daawat', 'kohinoor',
    'aashirvaad', 'saffola', 'fortune',
    'sundrop', 'dhara', 'goldwinner',
    'everest', 'mdh', 'catch', 'badshah',
    'mcvities', 'oreo',
    'prestige', 'hawkins', 'pigeon', 'butterfly',
    # NOTE: 'tr' is NOT here — "KITCHEN TR" = "Kitchen Treasure" brand (masala/spice),
    # but 'tr' alone appears as abbreviation in many unrelated items.
    # NOTE: 'ss' is NOT here — "SS PLATE" means Stainless Steel, handled by FMCG_ABBREVIATIONS.
}

# UPDATED: Full FMCG abbreviation map from real POS/billing data
# Key additions vs old version:
#   ftgr → fenugreek  (very common Kerala spice abbreviation)
#   ss   → stainless steel  (SS PLATE, SS OVAL etc.)
#   tr   → treasure  (KITCHEN TR = Kitchen Treasure masala brand)
#   nb, sc, mr → notebook/school/margin ruled (stationery)
#   butrscotch, jasmne, rsln, rsnlmn → food/puja items
FMCG_ABBREVIATIONS = {
    # Cleaning / household
    'btrm':       'bathroom',
    'clnr':       'cleaner',
    'clng':       'cleaning',
    'cnctrtd':    'concentrated',
    'disinftnt':  'disinfectant',
    'disnftnt':   'disinfectant',
    'lqd':        'liquid',
    'lm':         'lime',
    'grs':        'grease',
    'blk':        'black',
    'thndr':      'thunder',
    'florl':      'floral',
    'antibctrl':  'antibacterial',
    'xtra':       'extra',
    'tugh':       'tough',
    'det':        'detergent',
    'fab':        'fabric',
    'phnyl':      'phenyl',
    'dsinfct':    'disinfectant',
    'airfsh':     'air freshener',
    # Food / biscuits
    'cookis':     'cookies',
    'cashw':      'cashew',
    'digestve':   'digestive',
    'choco':      'chocolate',
    'van':        'vanilla',
    'vnlla':      'vanilla',
    'strbry':     'strawberry',
    'rasbry':     'raspberry',
    'bluebry':    'blueberry',
    'blkbry':     'blackberry',
    'butrscotch': 'butterscotch',
    'jasmne':     'jasmine',
    'ketch':      'ketchup',
    'rsln':       'rasalnu',
    'rsnlmn':     'rasalnu lemon',
    'ftgr':       'fenugreek',   # very common Kerala spice — methi seeds
    'podi':       'powder',
    'puttu':      'puttu flour',
    'matta':      'matta rice',
    # Personal care / cosmetics
    'shmp':       'shampoo',
    'shavng':     'shaving',
    'razr':       'razor',
    'wmn':        'women',
    'cndtnr':     'conditioner',
    'essnce':     'essence',
    'deo':        'deodorant',
    'ltn':        'lotion',
    # Containers / packaging
    'pch':        'pouch',
    'pckt':       'packet',
    'btl':        'bottle',
    'btf':        'bottle',
    'pet':        'plastic bottle',
    # Personal care (cream/lotion)
    'crm':        'cream',
    'pdr':        'powder',
    'clr':        'colour',
    # Stainless steel — SS prefix means Stainless Steel (SS PLATE, SS OVAL etc.)
    'ss':         'stainless steel',
    # Garments
    'plzz':       'palazzo',
    'dsgnr':      'designer',
    'mltclr':     'multicolour',
    'mutl':       'multicolour',
    'insltd':     'insulated',
    'lnchbag':    'lunch bag',
    # Footwear
    'dl':         'design',
    # Bags / accessories
    'kj':         'kids',
    # Umbrella
    'umbrla':     'umbrella',
    'telescop':   'telescopic',
    # Books / stationery
    'nb':         'notebook',
    'sc':         'school',
    'mr':         'margin ruled',
    'unrld':      'unruled',
    'pgs':        'pages',
    # Chicken / food
    'chkn':       'chicken',
    'brkfst':     'breakfast',
    # Floor / mat
    'flr':        'floor',
    'mat':        'floor mat',
    'mas':        'masala',
    # "KITCHEN TR" = Kitchen Treasure brand (masala/spice Ch 09)
    'tr':         'treasure',
    # Misc common
    'asstd':      'assorted',
    'asst':       'assorted',
    'refil':      'refill',
    'ltr':        'litre',
    'pks':        'packs',
    'assrtd':     'assorted',
    'fgr':        'finger',
    'agrbtti':    'agarbatti',
    'agrbati':    'agarbatti',
    'chand':      'chandan',
    'chndn':      'chandan sandalwood',
    'lnch':       'lunch',
    'kdu':        'kadukkai',
    'pck':        'pack',
    'sprng':      'spring',
    'nuggt':      'nugget',
}

# UPDATED: Rich synonym map covering all major categories
SYNONYMS = {
    # Basic common mappings
    'wash':       ['soap', 'cleanser', 'liquid'],
    'phone':      ['mobile', 'smartphone'],
    'tv':         ['television'],
    'fridge':     ['refrigerator'],
    'laptop':     ['notebook', 'computer'],
    'biscuit':    ['cookie', 'cracker', 'wafer', 'bakery'],
    'shirt':      ['tshirt', 'top', 'garment'],
    # FOOTWEAR (Ch 64) — 617 VKC items; vkc maps to footwear chapter
    'vkc':        ['footwear', 'sandal', 'slipper', 'shoe', 'chappal'],
    'footwear':   ['shoe', 'sandal', 'slipper', 'chappal', 'slippers'],
    'sandal':     ['slipper', 'footwear', 'chappal', 'hawai'],
    'slipper':    ['sandal', 'footwear', 'chappal', 'hawai'],
    'chappal':    ['sandal', 'slipper', 'footwear'],
    # PLASTICS (Ch 39)
    'container':  ['box', 'storage', 'jar', 'vessel', 'casserole'],
    'basket':     ['container', 'storage', 'laundry'],
    'hanger':     ['hook', 'clothes hanger'],
    'casserole':  ['container', 'insulated'],
    # STEEL / UTENSILS (Ch 73)
    'stainless':  ['steel', 'ss', 'inox', 'metal'],
    'steel':      ['stainless', 'metal', 'ss'],
    'utensil':    ['cookware', 'vessel', 'pan', 'pot', 'ladle'],
    'ladle':      ['spoon', 'spatula', 'utensil'],
    'spatula':    ['ladle', 'spoon', 'utensil'],
    'strainer':   ['sieve', 'filter', 'jali', 'colander'],
    # GLASS / DINNERWARE (Ch 70)
    'glassware':  ['dinner set', 'bowl', 'plate', 'mug', 'glass'],
    'cello':      ['glassware', 'dinner set', 'bowl', 'container'],
    # ALUMINIUM (Ch 76)
    'aluminium':  ['aluminum', 'alu', 'fry pan', 'mould', 'cookware'],
    # COSMETICS / PERSONAL CARE (Ch 33)
    'lipstick':   ['lip color', 'lip balm', 'lip gloss'],
    'fairness':   ['face cream', 'skin whitening', 'face wash'],
    'cream':      ['lotion', 'moisturizer', 'fairness', 'face'],
    'deodorant':  ['deo', 'body spray', 'antiperspirant', 'roll on'],
    'perfume':    ['fragrance', 'body spray', 'cologne', 'attar', 'fogg'],
    'fogg':       ['deodorant', 'body spray', 'perfume'],
    'agarbatti':  ['incense', 'dhoop', 'sambrani', 'agarbathi'],
    'agarbathi':  ['incense', 'agarbatti', 'dhoop'],
    # CLEANING (Ch 34)
    'detergent':  ['cleaner', 'washing powder', 'liquid', 'surf'],
    'phenyl':     ['floor cleaner', 'disinfectant', 'harpic', 'lysol'],
    'harpic':     ['toilet cleaner', 'bathroom cleaner', 'disinfectant'],
    'disinfectant': ['phenyl', 'cleaner', 'antiseptic', 'dettol'],
    # SHAMPOO (Ch 33)
    'shampoo':    ['hair wash', 'shmp', 'hair cleanser', 'hair care'],
    # FOOD GRAINS (Ch 10)
    'rice':       ['chawal', 'arisi', 'basmati', 'matta', 'sona masoori'],
    'basmati':    ['rice', 'long grain', 'biryani rice'],
    'matta':      ['rice', 'red rice', 'kerala rice', 'brown rice'],
    'wheat':      ['atta', 'flour', 'chakki', 'maida'],
    'atta':       ['wheat flour', 'chakki', 'whole wheat'],
    # SPICES (Ch 09)
    'turmeric':   ['haldi', 'manjal', 'curcuma', 'yellow powder'],
    'chilli':     ['chili', 'mirchi', 'red pepper', 'chilli powder'],
    'masala':     ['spice mix', 'powder', 'spices', 'blend'],
    'pepper':     ['peppercorn', 'kali mirch', 'milagu'],
    'cardamom':   ['elaichi', 'elakkai'],
    'cinnamon':   ['dalchini', 'pattai'],
    'fenugreek':  ['methi', 'vendayam', 'ftgr'],
    # OILS (Ch 15)
    'sesame':     ['gingelly', 'til oil', 'ellu', 'nallennai'],
    'gingelly':   ['sesame', 'til', 'ellu'],
    'coconut':    ['copra', 'narikela', 'thengai'],
    'sunflower':  ['saffola', 'sunflower oil'],
    'mustard':    ['sarson', 'kadugu', 'mustard oil'],
    'castor':     ['arandi', 'castor oil'],
    'puja':       ['oil', 'jasmine', 'sesame', 'lamp oil', 'pooja'],
    'pooja':      ['puja', 'oil', 'jasmine', 'lamp'],
    # DAIRY (Ch 04)
    'ghee':       ['clarified butter', 'fat', 'butter ghee'],
    'milk':       ['dairy', 'whitener', 'full cream', 'toned'],
    'butter':     ['dairy', 'fat'],
    'cheese':     ['dairy', 'paneer', 'processed cheese'],
    'paneer':     ['cheese', 'cottage cheese', 'dairy'],
    'yogurt':     ['curd', 'dahi', 'set curd'],
    'curd':       ['yogurt', 'dahi', 'set curd'],
    # BISCUITS / SNACKS (Ch 19)
    'cookie':     ['biscuit', 'wafer', 'cracker', 'digestive'],
    'wafer':      ['biscuit', 'cookie', 'chocolate wafer'],
    'chips':      ['snack', 'crisps', 'puff', 'extruded snack'],
    'puff':       ['chips', 'snack', 'corn puff', 'extruded'],
    # CHOCOLATE / CONFECTIONERY (Ch 17/18)
    'chocolate':  ['choco', 'cocoa', 'candy', 'bar'],
    'candy':      ['toffee', 'sweet', 'confectionery'],
    'jaggery':    ['gur', 'brown sugar', 'cane jaggery'],
    'sugar':      ['sucrose', 'cane sugar', 'jaggery'],
    # BEVERAGES (Ch 22)
    'aerated':    ['soft drink', 'pepsi', 'cola', 'soda'],
    'juice':      ['fruit juice', 'real juice', 'nectar'],
    # FISH / MEAT (Ch 02/03)
    'fish':       ['seafood', 'prawn', 'shrimp', 'kozhuva', 'sardine'],
    'prawn':      ['shrimp', 'fish', 'seafood'],
    'chicken':    ['poultry', 'meat', 'chkn', 'broiler'],
    # TOYS (Ch 95)
    'toy':        ['plaything', 'game', 'play set', 'doll', 'vehicle'],
    'doll':       ['toy', 'figurine', 'play'],
    'xmas':       ['christmas', 'x-mas', 'decoration', 'festive'],
    # STATIONERY (Ch 48/96)
    'notebook':   ['note book', 'exercise book', 'writing book', 'nb'],
    'pen':        ['ball pen', 'writing pen', 'gel pen', 'ink pen'],
    'pencil':     ['drawing pencil', 'hb pencil', 'graphite'],
    'eraser':     ['rubber eraser', 'correction'],
    # UMBRELLA (Ch 66)
    'umbrella':   ['rain umbrella', 'telescopic umbrella', 'umbrla'],
    # ICE CREAM (Ch 21)
    'ice cream':  ['kulfi', 'ice lolly', 'frozen dessert', 'fundae'],
    'lazza':      ['ice cream', 'frozen dessert', 'kulfi'],
    # PICKLE / CONDIMENTS (Ch 20/21)
    'pickle':     ['achar', 'pickled', 'brined', 'mango pickle'],
    'jam':        ['jelly', 'marmalade', 'fruit spread'],
    'ketchup':    ['sauce', 'tomato sauce', 'chilli sauce'],
    # SALT (Ch 25)
    'salt':       ['iodised salt', 'rock salt', 'pink salt', 'namak'],
    # CAMPHOR (Ch 29)
    'camphor':    ['karpoor', 'kapur', 'naphthalene'],
    # MATCH BOX (Ch 36)
    'match':      ['matchbox', 'safety match', 'fire match'],
    # CHRISTMAS (Ch 95)
    'christmas':  ['xmas', 'decoration', 'festive', 'x-mas tree'],
}

# UPDATED: Full domain prefix map — chapter hints from product tokens
DOMAIN_PREFIXES = {
    # FOOTWEAR (Ch 64) — 617 VKC items in dataset
    'footwear': ['64'], 'shoe': ['64'], 'sandal': ['64'],
    'slipper': ['64'], 'chappal': ['64'], 'vkc': ['64'],
    'hawai': ['64'], 'flipflop': ['64'],
    # PLASTICS (Ch 39)
    'container': ['39'], 'basket': ['39'], 'hanger': ['39'],
    'plastic': ['39'], 'casserole': ['39'], 'laundry': ['39'],
    'dustbin': ['39'], 'bucket': ['39'],
    # STEEL UTENSILS (Ch 73)
    'stainless': ['73'], 'steel': ['73'],
    'utensil': ['73', '76', '69', '70'],
    'ladle': ['73', '82'], 'spatula': ['73', '82'],
    'strainer': ['73', '82'], 'tongs': ['73', '82'],
    # ALUMINIUM (Ch 76)
    'aluminium': ['76'], 'aluminum': ['76'],
    # GLASS / DINNER SET (Ch 70)
    'glassware': ['70'], 'ceramic': ['69'], 'porcelain': ['69'],
    # COSMETICS / PERSONAL CARE (Ch 33)
    'cosmetic': ['33'], 'makeup': ['33'], 'skincare': ['33'],
    'skin': ['33'], 'toothpaste': ['33'], 'agarbatti': ['33'],
    'agarbathi': ['33'], 'incense': ['33'], 'perfume': ['33'],
    'deodorant': ['33'], 'fogg': ['33'], 'lipstick': ['33'],
    'fairness': ['33'], 'shampoo': ['33'], 'conditioner': ['33'],
    'hair oil': ['33'], 'body lotion': ['33'],
    # SOAP / DETERGENT (Ch 34)
    'soap': ['34', '33'], 'detergent': ['34'], 'phenyl': ['34'],
    'disinfectant': ['34'], 'bleach': ['34'], 'harpic': ['34'],
    'cleaning': ['34'], 'cleaner': ['34'],
    'dishwash': ['34'], 'dishwasher': ['34'],
    # TOOTHBRUSH / PEN / BRUSH (Ch 96)
    'toothbrush': ['96'], 'brush': ['96'], 'pen': ['96'],
    'pencil': ['96'], 'eraser': ['96'], 'sharpener': ['96'],
    'marker': ['96'],
    # TOYS (Ch 95)
    'toy': ['95'], 'doll': ['95'], 'game': ['95'],
    'christmas': ['95'], 'xmas': ['95'], 'balloon': ['95'],
    'puzzle': ['95'],
    # NOTEBOOK / PAPER (Ch 48)
    'notebook': ['48'], 'paper': ['48'], 'envelope': ['48'],
    'stationery': ['48', '96'],
    # BOOKS (Ch 49)
    'book': ['48', '49'], 'textbook': ['49'],
    # FOOD GRAINS (Ch 10)
    'rice': ['10'], 'basmati': ['10'], 'matta': ['10'],
    'wheat': ['10', '11'], 'oats': ['10', '11'], 'barley': ['10'],
    # FLOUR / CEREAL (Ch 11)
    'atta': ['11'], 'flour': ['11'], 'maida': ['11'],
    'suji': ['11'], 'rava': ['11'], 'poha': ['11'],
    'aval': ['11'], 'puttupodi': ['11'],
    # DAIRY (Ch 04)
    'milk': ['04'], 'ghee': ['04'], 'butter': ['04'],
    'cheese': ['04'], 'paneer': ['04'], 'yogurt': ['04'],
    'curd': ['04'], 'cream': ['04', '33'], 'egg': ['04'],
    'dairy': ['04'],
    # SPICES (Ch 09)
    'masala': ['09'], 'spice': ['09'], 'turmeric': ['09'],
    'chilli': ['09'], 'pepper': ['09'], 'cardamom': ['09'],
    'cinnamon': ['09'], 'fenugreek': ['09'], 'ginger': ['09'],
    'coriander': ['09'],
    # OILS (Ch 15) — puja oil included; 'puja' alone → Ch15/33 via CATEGORY_RULES
    'oil': ['15'], 'sesame': ['15'], 'gingelly': ['15'],
    'sunflower': ['15'], 'mustard oil': ['15'], 'castor': ['15'],
    'vanaspati': ['15'], 'palm oil': ['15'],
    # BISCUITS / BAKERY (Ch 19)
    'biscuit': ['19'], 'cookie': ['19'], 'wafer': ['19'],
    'chips': ['19'], 'puff': ['19'], 'snack': ['19'],
    'cereal': ['19'], 'popcorn': ['19'], 'noodle': ['19'],
    'pasta': ['19'], 'bread': ['19'],
    # CHOCOLATE / COCOA (Ch 18)
    'chocolate': ['18'], 'cocoa': ['18'],
    # CONFECTIONERY (Ch 17)
    'sugar': ['17'], 'jaggery': ['17'], 'candy': ['17'], 'toffee': ['17'],
    # PICKLE / JAM (Ch 20)
    'pickle': ['20'], 'jam': ['20'], 'jelly': ['20'], 'preserve': ['20'],
    # SAUCES / CONDIMENTS / ICE CREAM (Ch 21)
    'ketchup': ['21'], 'sauce': ['21'], 'mayonnaise': ['21'],
    'vinegar': ['21'], 'ice cream': ['21'],
    # BEVERAGES (Ch 22)
    'aerated': ['22'], 'soft drink': ['22'], 'juice': ['20', '22'],
    'water': ['22'], 'soda': ['22'],
    # FISH / SEAFOOD (Ch 03)
    'fish': ['03'], 'prawn': ['03'], 'seafood': ['03'], 'shrimp': ['03'],
    # MEAT / POULTRY (Ch 02)
    'chicken': ['02'], 'meat': ['02'],
    # SALT (Ch 25)
    'salt': ['25'],
    # CAMPHOR (Ch 29)
    'camphor': ['29'],
    # MATCH BOX (Ch 36)
    'match': ['36'], 'matchbox': ['36'],
    # BLADES / KNIVES (Ch 82)
    'razor': ['82'], 'blade': ['82'], 'knife': ['82'],
    'scissors': ['82'], 'cutter': ['82'],
    # COMPUTER / MACHINES (Ch 84)
    'computer': ['84'], 'laptop': ['84'], 'stapler': ['84'],
    # ELECTRONICS (Ch 85)
    'phone': ['85'], 'mobile': ['85'], 'smartphone': ['85'],
    'television': ['85'],
    # LIGHTS / LAMPS (Ch 94)
    'bulb': ['94'], 'led': ['94'], 'light': ['94'],
    # UMBRELLA (Ch 66)
    'umbrella': ['66'],
    # FOOTWEAR PARTS (Ch 64)
    'insole': ['64'],
}

# UPDATED: Priority-ordered category rules — first match wins
# Key fixes vs old version:
#   • puja/pooja now → Ch15/33 (was Ch33 only — puja oil should be Ch15)
#   • agarbatti → Ch33 added (was missing)
#   • footwear (vkc, sandal, chappal, hawai) → Ch64 added
#   • toys/xmas/balloon → Ch95 added
#   • steel/aluminium/plastic → Ch73/76/39 added
#   • Kerala-specific: matta, aval, puttupodi → Ch10/11
#   • camphor → Ch29, matchbox → Ch36 (was incorrectly Ch39)
CATEGORY_RULES = [
    # HIGH PRIORITY (first match wins)
    {'keywords': ['tooth', 'paste', 'toothpaste', 'dentifrice'],   'chapters': ['33'], 'description': 'toothpaste -> Ch33'},
    {'keywords': ['toothbrush', 'tbrush'],                          'chapters': ['96'], 'description': 'toothbrush -> Ch96'},
    {'keywords': ['note', 'book', 'notebook', 'copybook'],          'chapters': ['48'], 'description': 'notebook -> Ch48'},
    # puja oil → Ch15 (not Ch33) — "PUJA OIL" is lamp oil, not cosmetic
    {'keywords': ['puja', 'pooja', 'thiri', 'wick', 'lamp oil'],    'chapters': ['15', '33'], 'description': 'puja items -> Ch15/33'},
    {'keywords': ['agarbatti', 'agarbathi', 'incense', 'sambrani'], 'chapters': ['33'], 'description': 'incense -> Ch33'},
    {'keywords': ['cleaning', 'cleaner', 'detergent', 'phenyl', 'disinfectant', 'harpic'], 'chapters': ['34'], 'description': 'cleaning -> Ch34'},
    {'keywords': ['cosmetic', 'makeup', 'skincare', 'foundation', 'kajal', 'eyeshadow'], 'chapters': ['33'], 'description': 'cosmetics -> Ch33'},
    {'keywords': ['soap', 'toilet soap'],                           'chapters': ['34', '33'], 'description': 'soap -> Ch34/33'},
    {'keywords': ['shampoo', 'conditioner', 'hair wash'],           'chapters': ['33'], 'description': 'shampoo -> Ch33'},
    {'keywords': ['phone', 'mobile', 'smartphone'],                 'chapters': ['85'], 'description': 'phones -> Ch85'},
    {'keywords': ['television', 'tv'],                              'chapters': ['85'], 'description': 'TV -> Ch85'},
    {'keywords': ['computer', 'laptop'],                            'chapters': ['84'], 'description': 'computers -> Ch84'},
    {'keywords': ['fridge', 'refrigerator'],                        'chapters': ['84'], 'description': 'refrigerators -> Ch84'},
    # VKC footwear — largest single brand (603 items) — must route to Ch64
    {'keywords': ['vkc', 'footwear', 'sandal', 'slipper', 'chappal', 'shoe', 'hawai'], 'chapters': ['64'], 'description': 'footwear -> Ch64'},
    {'keywords': ['toy', 'doll', 'puzzle', 'balloon', 'xmas', 'christmas'], 'chapters': ['95'], 'description': 'toys -> Ch95'},
    {'keywords': ['pen', 'pencil', 'eraser', 'marker', 'highlighter'], 'chapters': ['96'], 'description': 'stationery pen -> Ch96'},
    {'keywords': ['umbrella', 'umbrla'],                            'chapters': ['66'], 'description': 'umbrella -> Ch66'},
    {'keywords': ['match', 'matchbox', 'safety match'],             'chapters': ['36'], 'description': 'matchbox -> Ch36 (NOT Ch39)'},
    {'keywords': ['camphor', 'karpoor'],                            'chapters': ['29'], 'description': 'camphor -> Ch29 (NOT Ch33)'},
    # LOWER PRIORITY
    {'keywords': ['oil'],                                           'chapters': ['15'], 'description': 'oil -> Ch15 (default)'},
    {'keywords': ['food', 'beverage', 'drink'],                     'chapters': ['04', '19', '20', '21', '22'], 'description': 'food/bev -> Ch04/19-22'},
    {'keywords': ['clothing', 'garment', 'fabric', 'pants', 'shirt', 'palazzo'], 'chapters': ['61', '62', '63'], 'description': 'clothing -> Ch61-63'},
    {'keywords': ['furniture', 'sofa', 'chair', 'table'],          'chapters': ['94'], 'description': 'furniture -> Ch94'},
    {'keywords': ['steel', 'stainless'],                            'chapters': ['73'], 'description': 'steel -> Ch73'},
    {'keywords': ['aluminium', 'aluminum'],                         'chapters': ['76'], 'description': 'aluminium -> Ch76'},
    {'keywords': ['plastic', 'container', 'basket', 'hanger'],     'chapters': ['39'], 'description': 'plastics -> Ch39'},
    {'keywords': ['glass', 'ceramic', 'porcelain'],                 'chapters': ['70', '69'], 'description': 'glass/ceramic -> Ch70/69'},
    {'keywords': ['rice', 'basmati', 'matta'],                      'chapters': ['10'], 'description': 'rice -> Ch10'},
    {'keywords': ['atta', 'flour', 'maida', 'suji', 'rava', 'puttupodi', 'aval', 'poha'], 'chapters': ['11'], 'description': 'flour -> Ch11'},
    {'keywords': ['spice', 'masala', 'turmeric', 'chilli', 'pepper', 'cardamom'], 'chapters': ['09'], 'description': 'spices -> Ch09'},
    {'keywords': ['chocolate', 'cocoa', 'choco'],                   'chapters': ['18'], 'description': 'chocolate -> Ch18'},
    {'keywords': ['biscuit', 'cookie', 'wafer', 'chips', 'puff', 'snack', 'cereal', 'popcorn'], 'chapters': ['19'], 'description': 'snacks -> Ch19'},
    {'keywords': ['sugar', 'jaggery', 'candy', 'toffee'],           'chapters': ['17'], 'description': 'sugar/candy -> Ch17'},
    {'keywords': ['dairy', 'milk', 'ghee', 'butter', 'cheese', 'paneer', 'curd', 'yogurt'], 'chapters': ['04'], 'description': 'dairy -> Ch04'},
    {'keywords': ['fish', 'prawn', 'seafood', 'shrimp'],            'chapters': ['03'], 'description': 'seafood -> Ch03'},
    {'keywords': ['chicken', 'meat', 'poultry'],                    'chapters': ['02'], 'description': 'meat -> Ch02'},
    {'keywords': ['knife', 'scissors', 'razor', 'blade', 'cutter'], 'chapters': ['82'], 'description': 'blades -> Ch82'},
    {'keywords': ['salt', 'iodised salt'],                          'chapters': ['25'], 'description': 'salt -> Ch25'},
    {'keywords': ['pickle', 'achar'],                               'chapters': ['20'], 'description': 'pickle -> Ch20'},
    {'keywords': ['jam', 'jelly', 'marmalade'],                     'chapters': ['20'], 'description': 'jam -> Ch20'},
    {'keywords': ['ketchup', 'sauce', 'ice cream', 'supplement'],   'chapters': ['21'], 'description': 'condiments/icecream -> Ch21'},
    {'keywords': ['juice', 'aerated', 'soft drink', 'water', 'soda'], 'chapters': ['22'], 'description': 'beverages -> Ch22'},
]

# ── Helper functions ───────────────────────────────────────────────────────────

def expand_fmcg_abbreviations(text: str) -> str:
    """Expand FMCG abbreviations word-by-word (case-insensitive)."""
    words = text.split()
    expanded_words = []
    for word in words:
        lower_word = word.lower()
        if lower_word in FMCG_ABBREVIATIONS:
            expanded_words.append(FMCG_ABBREVIATIONS[lower_word])
        else:
            expanded_words.append(word)
    return ' '.join(expanded_words)


def tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r'\b\d+\s*(ml|g|gm|kg|l|ltr|mg|oz|lb|pc|pcs|nos)\b', ' ', text)
    text = re.sub(r'\b\d+\b', ' ', text)
    tokens = re.findall(r'[a-z]{2,}', text)
    return [t for t in tokens if t not in STOPWORDS and t not in BRANDS and len(t) >= 2]


def detect_category_restrictions(tokens: list[str]) -> list[str]:
    """Return restricted HSN chapters for the first matching category rule."""
    for rule in CATEGORY_RULES:
        if any(keyword in tokens for keyword in rule['keywords']):
            return rule['chapters']
    return []


def build_hsn_prefix_clause(tokens: list[str]) -> tuple[str, dict]:
    """Build a SQL WHERE clause fragment to restrict results to likely HSN chapters."""
    expanded_tokens = set(tokens)
    for token in tokens:
        expanded_tokens.update(SYNONYMS.get(token, []))

    # Category rules take priority over generic domain prefixes
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
        # tsquery tokens must be single words; skip multi-word synonyms
        single_word_variants = [v for v in variants if ' ' not in v]
        if len(single_word_variants) > 1:
            query_terms.append("(" + " | ".join(single_word_variants) + ")")
        else:
            query_terms.append(token)
    return query_terms


def compute_weighted_jaccard(tokens: list[str], desc_tokens: set[str]) -> float:
    """Weighted Jaccard similarity — query tokens weighted 2x, synonyms 1x."""
    query_weights: dict[str, int] = {}
    for token in tokens:
        query_weights[token] = max(query_weights.get(token, 0), 2)
        for synonym in SYNONYMS.get(token, []):
            query_weights[synonym] = max(query_weights.get(synonym, 0), 1)

    intersection_weight = sum(
        weight for term, weight in query_weights.items() if term in desc_tokens
    )
    union_weight = sum(query_weights.values()) + len(desc_tokens) - intersection_weight
    return intersection_weight / union_weight if union_weight else 0.0


# ── Core matching logic ────────────────────────────────────────────────────────
async def _match_one(query: str, db: AsyncSession) -> HSNBatchResult:
    """
    Multi-pass HSN matching.

    Pass 0: Verified products table (exact + trigram) — highest accuracy,
            covers all 13,864 known trade invoice products.
    Pass 1: Exact HSN code match (numeric input).
    Pass 2: Full-text search via hsn_search.search_vector (GIN index).
    Pass 3: Trigram similarity on hsn_search.normalized_description.
    Pass 4: ILIKE keyword fallback on hsn_codes.description.

    GST rate is always taken from hsn_codes.gst_rate (the corrected column),
    never from the original product data column which may have errors.
    """
    q_stripped = query.strip()

    # ── Pass 0: Verified products lookup ──────────────────────────────────────
    # Exact match first, then trigram fallback at similarity >= 0.6
    # This covers all 13,864 products from correct_datas.xlsx with ground-truth
    # HSN codes (column 5 = HSN As per GST) and GST rates (column 6 = GST As per GST).
    try:
        q_lower = q_stripped.lower()
        # Exact description match
        vp_res = await db.execute(
            text("""
                SELECT
                    vp.hsn_code,
                    h.description,
                    h.gst_rate,
                    h.category,
                    1.0 AS sim
                FROM verified_products vp
                JOIN hsn_codes h ON h.hsn_code = vp.hsn_code
                WHERE lower(vp.description_normalized) = :q
                LIMIT 1
            """),
            {"q": q_lower}
        )
        vp_row = vp_res.fetchone()

        if not vp_row:
            # Trigram similarity match against verified products
            vp_res = await db.execute(
                text("""
                    SELECT
                        vp.hsn_code,
                        h.description,
                        h.gst_rate,
                        h.category,
                        similarity(vp.description_normalized, :q) AS sim
                    FROM verified_products vp
                    JOIN hsn_codes h ON h.hsn_code = vp.hsn_code
                    WHERE vp.description_normalized % :q
                    ORDER BY sim DESC
                    LIMIT 1
                """),
                {"q": q_lower}
            )
            vp_row = vp_res.fetchone()

        if vp_row and float(vp_row.sim) >= 0.6:
            return HSNBatchResult(
                query=query,
                hsn_code=normalize_hsn(vp_row.hsn_code),
                description=vp_row.description,
                gst_rate=float(vp_row.gst_rate or 0),
                confidence=round(float(vp_row.sim), 3),
                confidence_label="high" if float(vp_row.sim) >= 0.85 else "medium",
                match_method="verified_products",
            )
    except Exception:
        # verified_products table may not exist yet — fall through gracefully
        pass

    # ── Pass 1: exact HSN code lookup ─────────────────────────────────────────
    if re.match(r'^\d{4,8}$', q_stripped):
        res = await db.execute(
            text("""
                SELECT h.hsn_code, h.description, h.gst_rate, h.category
                FROM hsn_codes h
                WHERE h.hsn_code = :code AND h.is_active = TRUE
                LIMIT 1
            """),
            {"code": q_stripped}
        )
        row = res.fetchone()
        if row:
            return HSNBatchResult(
                query=query,
                hsn_code=normalize_hsn(row.hsn_code),   # FIX: normalize
                description=row.description,
                gst_rate=float(row.gst_rate or 0),
                confidence=1.0,
                confidence_label="high",
                match_method="exact_code",
            )

    # Expand abbreviations then tokenize
    q_expanded = expand_fmcg_abbreviations(q_stripped)
    tokens = tokenize(q_expanded)
    if not tokens:
        return HSNBatchResult(query=query, match_method="none")

    domain_clause, domain_params = build_hsn_prefix_clause(tokens)

    # ── Pass 2: Full-text search via hsn_search.search_vector ────────────────
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
            query_params
        )
        rows_fts = res.fetchall()
    except Exception:
        rows_fts = []

    # Fallback: OR query if AND returned nothing
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
                query_params
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
            jaccard_weighted = jaccard * 0.6
            final_score = min(jaccard_weighted + fts_score, 1.0)

            entry = {
                "hsn_code": normalize_hsn(r.hsn_code),  # FIX: normalize
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

    # ── Pass 3: Trigram similarity on hsn_search.normalized_description ───────
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
            {"q": trgm_query, **domain_params}
        )
        rows_trgm = res.fetchall()
    except Exception:
        rows_trgm = []

    if rows_trgm:
        best = rows_trgm[0]
        sim_score = float(best.sim)
        alts = [
            {
                "hsn_code": normalize_hsn(r.hsn_code),  # FIX: normalize
                "description": r.description,
                "gst_rate": float(r.gst_rate or 0),
                "confidence": round(float(r.sim), 3),
            }
            for r in rows_trgm[1:4]
        ]
        if sim_score > 0.15:
            label = "high" if sim_score >= 0.60 else ("medium" if sim_score >= 0.30 else "low")
            return HSNBatchResult(
                query=query,
                hsn_code=normalize_hsn(best.hsn_code),  # FIX: normalize
                description=best.description,
                gst_rate=float(best.gst_rate or 0),
                confidence=round(sim_score, 3),
                confidence_label=label,
                match_method="trigram",
                alternatives=alts,
            )

    # ── Pass 4: ILIKE keyword fallback ────────────────────────────────────────
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
            {"pat": f"%{token}%", **domain_params}
        )
        for r in res.fetchall():
            key = normalize_hsn(r.hsn_code)  # FIX: normalize key
            if key not in candidates:
                candidates[key] = {
                    "hsn_code": key,
                    "description": r.description,
                    "gst_rate": float(r.gst_rate or 0),
                    "hits": 0,
                }
            candidates[key]["hits"] += 1

    if candidates:
        total_tokens = max(len(tokens), 1)
        scored = sorted(
            [(c["hits"] / total_tokens, c) for c in candidates.values()],
            key=lambda x: x[0],
            reverse=True,
        )
        top_score, top_c = scored[0]
        if top_score > 0.1:
            label = "high" if top_score >= 0.65 else ("medium" if top_score >= 0.35 else "low")
            alts = [
                {"hsn_code": c["hsn_code"], "description": c["description"],
                 "gst_rate": c["gst_rate"], "confidence": round(s, 3)}
                for s, c in scored[1:4] if s > 0
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


# ── Startup ────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    """
    Create only the users table if missing.
    DO NOT touch hsn_codes / hsn_search — they already exist in Neon
    with the correct schema, indexes, and ~10,957 records.
    verified_products is seeded separately via data/seed_verified.py.
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
