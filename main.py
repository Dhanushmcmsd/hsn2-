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
import os, json, re, uuid, math

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("hsn_main")

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
def normalize_hsn(code: str) -> str:
    if not code or not str(code).strip():
        return code
    stripped = str(code).strip()
    if re.match(r'^\d+$', stripped):
        return stripped.zfill(8)
    return stripped

# ── Size-stripping ────────────────────────────────────────────────────────────
_SIZE_PAT = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|'
    r'PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB)\b'
    r'|\b\d+\s*X\s*\d+\b'
    r'|\b\d+\s*\+\s*\d+\b'
    r'|\b\d+S\b|\b\d+N\b|\b\d+P\b'
    r'|\b\d+\b',
    re.IGNORECASE,
)

def _strip_sizes(text: str) -> str:
    t = _SIZE_PAT.sub(' ', text.upper())
    t = re.sub(r'[^A-Z\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

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
app = FastAPI(title="HSN Classifier API", version="2.3.0")

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
        result = await db.execute(text("SELECT COUNT(*) FROM hsn_codes WHERE is_active = TRUE"))
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
        "version": "2.3.0",
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
            "hsn_code": normalize_hsn(r.hsn_code),
            "description": r.description,
            "gst_rate": float(r.gst_rate or 0),
            "category": r.category,
        }
        for r in result.fetchall()
    ]

@app.post("/expand-abbreviations")
async def expand_abbreviations_endpoint(body: SingleQuery):
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
                "hsn_code": normalize_hsn(a.get("hsn_code", "")),
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
            if row.hsn_code:
                row.hsn_code = normalize_hsn(row.hsn_code)
            for alt in row.alternatives:
                if alt.get("hsn_code"):
                    alt["hsn_code"] = normalize_hsn(alt["hsn_code"])
            results.append(row)
        except Exception as e:
            log.error("batch.match_failed query=%s error=%s", query[:60], str(e))
            results.append(HSNBatchResult(query=query, error=str(e)))

    matched = sum(1 for r in results if r.hsn_code)
    return BatchResponse(
        results=results,
        total=len(results),
        matched=matched,
        unmatched=len(results) - matched,
    )

# ── Matching dictionaries ─────────────────────────────────────────────────────

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
    'normal','usual','common','rare','unique','ordinary','general','specific',
    'no1','no2','grade','quality','type','variety','model','make',
    'cover','wrapper','wt','weight','net','gross',
}

BRANDS = {
    'vkc','cello','manak','lemam','apaar','gebi','nolta','bees','polyset',
    'nakoda','esquire','real1','brillar','orgello','lazza','jaipet','sithas',
    'skei','ustraa','mercely','mercelyn','homwow','impex','firmer',
    'topclean','ksk','kvg','kshethra','keli','muram','liya','heyday','cupid',
    'alfa','colombo','flair','camlin','classmate','navneet','kangaro','bakers',
    'chozen','grandmas','diva','brahmins','eastern',
    'patanjali','nestle','amul','tata','godrej','dettol','lifebuoy','colgate',
    'pepsodent','nivea','garnier','loreal','sony','samsung','apple','lg',
    'whirlpool','philips','nike','adidas','puma','reebok','bajaj','marico',
    'unilever','parle','britannia','honda','suzuki','himalaya','dove','yardley',
    'gillette','pampers','huggies','johnson','dabur','emami','meril',
    'harpic','lizol','ariel','surf','rin','vim','haldirams','bikano','bikaji',
    'balaji','prataap','maggi','knorr','kissan','sunfeast','horlicks',
    'bournvita','complan','pediasure','boost','cadbury','milkybar','kitkat',
    'lays','kurkure','pringles','pepsi','sprite','fanta','maaza',
    'tropicana','paperboat','milkymist','heritage','moov','volini','iodex','burnol',
    'fogg','axe','engage','maybelline','lakme','revlon','cinthol','liril','lux',
    'pears','head','pantene','sunsilk','tresemme','odonil','odomos','mortein',
    'baygon','hit','fevicol','fevistick','fevikwik','pidilite','nataraj','apsara',
    'faber','staedtler','orbit','mentos','alpenliebe','indiagate','daawat',
    'kohinoor','aashirvaad','saffola','fortune','sundrop','dhara','goldwinner',
    'everest','mdh','catch','badshah','mcvities','oreo','prestige','hawkins',
    'pigeon','butterfly','pavithram','idhayam','suriyan','forma','dev','sithas',
    'thalolam','paf','lion','aachi','kissan','happy','priyom','fruitomans',
    'craze','unibic','bauli','elko','pearl','indigate','noltai','suryan',
    'crazee','urbans','daileco','om','shanthi','natural','spices',
}

FMCG_ABBREVIATIONS = {
    'btrm': 'bathroom', 'bthrm': 'bathroom', 'clnr': 'cleaner',
    'clng': 'cleaning', 'cnctrtd': 'concentrated', 'disinftnt': 'disinfectant',
    'disnftnt': 'disinfectant', 'disinft': 'disinfectant', 'disnft': 'disinfectant',
    'lqd': 'liquid', 'lm': 'lime', 'grs': 'grease', 'blk': 'black',
    'thndr': 'thunder', 'florl': 'floral', 'antibctrl': 'antibacterial',
    'xtra': 'extra', 'tugh': 'tough', 'det': 'detergent', 'fab': 'fabric',
    'phnyl': 'phenyl', 'dsinfct': 'disinfectant', 'airfsh': 'air freshener',
    'toilt': 'toilet', 'tolt': 'toilet', 'tlot': 'toilet', 'tlt': 'toilet',
    'clnr': 'cleaner', 'clnsng': 'cleansing',
    'cookis': 'cookies', 'cooki': 'cookie', 'cashw': 'cashew',
    'digestve': 'digestive', 'choc': 'chocolate', 'choco': 'chocolate',
    'van': 'vanilla', 'vnlla': 'vanilla', 'strbry': 'strawberry',
    'rasbry': 'raspberry', 'bluebry': 'blueberry', 'blkbry': 'blackberry',
    'butrscotch': 'butterscotch', 'jasmne': 'jasmine', 'ketch': 'ketchup',
    'ftgr': 'fenugreek', 'podi': 'powder', 'puttu': 'puttu flour',
    'matta': 'matta rice', 'shmp': 'shampoo', 'shavng': 'shaving',
    'razr': 'razor', 'wmn': 'women', 'cndtnr': 'conditioner',
    'essnce': 'essence', 'deo': 'deodorant', 'ltn': 'lotion',
    'pch': 'pouch', 'pckt': 'packet', 'btl': 'bottle', 'btf': 'bottle',
    'pet': 'plastic bottle', 'crm': 'cream', 'pdr': 'powder',
    'clr': 'colour', 'ss': 'stainless steel', 'plzz': 'palazzo',
    'dsgnr': 'designer', 'mltclr': 'multicolour', 'mutl': 'multicolour',
    'insltd': 'insulated', 'lnchbag': 'lunch bag', 'dl': 'design',
    'kj': 'kids', 'umbrla': 'umbrella', 'telescop': 'telescopic',
    'nb': 'notebook', 'sc': 'school', 'mr': 'margin ruled',
    'unrld': 'unruled', 'pgs': 'pages', 'chkn': 'chicken',
    'brkfst': 'breakfast', 'flr': 'floor', 'mat': 'floor mat',
    'mas': 'masala', 'tr': 'treasure', 'asstd': 'assorted',
    'asst': 'assorted', 'refil': 'refill', 'ltr': 'litre',
    'pks': 'packs', 'assrtd': 'assorted', 'fgr': 'finger',
    'agrbtti': 'agarbatti', 'agrbati': 'agarbatti', 'chand': 'chandan',
    'chndn': 'chandan sandalwood', 'lnch': 'lunch', 'kdu': 'kadukkai',
    'pck': 'pack', 'sprng': 'spring', 'nuggt': 'nugget',
    'pwr': 'power', 'plus': 'plus', 'orig': 'original', 'orgnl': 'original',
    'orgnc': 'organic', 'act': 'active', 'actv': 'active',
    'hygnc': 'hygienic', 'hygienc': 'hygienic', 'rim': 'rim',
    'flushmtic': 'flushmatic', 'cistrn': 'cistern',
    'marin': 'marine', 'jasmn': 'jasmine', 'lemn': 'lemon',
    'parijta': 'parijata', 'parijt': 'parijata',
    'wht': 'white', 'whn': 'when', 'whi': 'whitening',
    'whitenshн': 'whitening', 'whiten': 'whitening',
    'germnstain': 'germ stain', 'blaster': 'blaster',
    'iodised': 'iodized', 'brandedjaggry': 'jaggery',
    'nc': 'nice', 'noltai': 'nolta',
}

SYNONYMS = {
    'wash': ['soap', 'cleanser', 'liquid'],
    'phone': ['mobile', 'smartphone'],
    'tv': ['television'],
    'fridge': ['refrigerator'],
    'laptop': ['computer'],
    'biscuit': ['cookie', 'cracker', 'wafer', 'bakery'],
    'shirt': ['tshirt', 'top', 'garment'],
    'vkc': ['footwear', 'sandal', 'slipper', 'shoe', 'chappal'],
    'footwear': ['shoe', 'sandal', 'slipper', 'chappal', 'slippers'],
    'sandal': ['slipper', 'footwear', 'chappal', 'hawai'],
    'slipper': ['sandal', 'footwear', 'chappal', 'hawai'],
    'chappal': ['sandal', 'slipper', 'footwear'],
    'container': ['box', 'storage', 'jar', 'vessel', 'casserole'],
    'basket': ['container', 'storage', 'laundry'],
    'hanger': ['hook', 'clothes hanger'],
    'casserole': ['container', 'insulated'],
    'stainless': ['steel', 'ss', 'inox', 'metal'],
    'steel': ['stainless', 'metal', 'ss'],
    'utensil': ['cookware', 'vessel', 'pan', 'pot', 'ladle'],
    'ladle': ['spoon', 'spatula', 'utensil'],
    'spatula': ['ladle', 'spoon', 'utensil'],
    'strainer': ['sieve', 'filter', 'jali', 'colander'],
    'glassware': ['dinner set', 'bowl', 'plate', 'mug', 'glass'],
    'cosmetic': ['makeup', 'beauty', 'skincare'],
    'lipstick': ['lip color', 'lip balm', 'lip gloss'],
    'fairness': ['face cream', 'skin whitening', 'face wash'],
    'cream': ['lotion', 'moisturizer', 'fairness', 'face'],
    'deodorant': ['deo', 'body spray', 'antiperspirant', 'roll on'],
    'perfume': ['fragrance', 'body spray', 'cologne', 'attar', 'fogg'],
    'fogg': ['deodorant', 'body spray', 'perfume'],
    'agarbatti': ['incense', 'dhoop', 'sambrani', 'agarbathi'],
    'agarbathi': ['incense', 'agarbatti', 'dhoop'],
    'detergent': ['cleaner', 'washing powder', 'liquid', 'surf'],
    'phenyl': ['floor cleaner', 'disinfectant', 'harpic', 'lysol'],
    'harpic': ['toilet cleaner', 'bathroom cleaner', 'disinfectant'],
    'disinfectant': ['phenyl', 'cleaner', 'antiseptic', 'dettol'],
    'shampoo': ['hair wash', 'shmp', 'hair cleanser', 'hair care'],
    'rice': ['chawal', 'arisi', 'basmati', 'matta', 'sona masoori'],
    'basmati': ['rice', 'long grain', 'biryani rice'],
    'matta': ['rice', 'red rice', 'kerala rice', 'brown rice'],
    'wheat': ['atta', 'flour', 'chakki', 'maida'],
    'atta': ['wheat flour', 'chakki', 'whole wheat'],
    'turmeric': ['haldi', 'manjal', 'curcuma', 'yellow powder'],
    'chilli': ['chili', 'mirchi', 'red pepper', 'chilli powder'],
    'masala': ['spice mix', 'powder', 'spices', 'blend'],
    'pepper': ['peppercorn', 'kali mirch', 'milagu'],
    'cardamom': ['elaichi', 'elakkai'],
    'cinnamon': ['dalchini', 'pattai'],
    'fenugreek': ['methi', 'vendayam', 'ftgr'],
    'sesame': ['gingelly', 'til oil', 'ellu', 'nallennai', 'sesame oil', 'sesame candy'],
    'gingelly': ['sesame', 'til', 'ellu'],
    'coconut': ['copra', 'narikela', 'thengai'],
    'sunflower': ['saffola', 'sunflower oil'],
    'mustard': ['sarson', 'kadugu', 'mustard oil'],
    'castor': ['arandi', 'castor oil'],
    'puja': ['oil', 'jasmine', 'sesame', 'lamp oil', 'pooja'],
    'pooja': ['puja', 'oil', 'jasmine', 'lamp'],
    'ghee': ['clarified butter', 'fat', 'butter ghee'],
    'milk': ['dairy', 'whitener', 'full cream', 'toned'],
    'butter': ['dairy', 'fat'],
    'cheese': ['dairy', 'paneer', 'processed cheese'],
    'paneer': ['cheese', 'cottage cheese', 'dairy'],
    'yogurt': ['curd', 'dahi', 'set curd'],
    'curd': ['yogurt', 'dahi', 'set curd'],
    'cookie': ['biscuit', 'wafer', 'cracker', 'digestive', 'cookies', 'cooki'],
    'cooki': ['cookie', 'biscuit', 'wafer', 'cracker', 'cookies'],
    'cashew': ['cashw', 'kaju'],
    'cashw': ['cashew', 'kaju'],
    'wafer': ['biscuit', 'cookie', 'chocolate wafer'],
    'chips': ['snack', 'crisps', 'puff', 'extruded snack'],
    'puff': ['chips', 'snack', 'corn puff', 'extruded'],
    'chocolate': ['choco', 'cocoa', 'candy', 'bar'],
    'candy': ['toffee', 'sweet', 'confectionery'],
    'jaggery': ['gur', 'brown sugar', 'cane jaggery'],
    'sugar': ['sucrose', 'cane sugar', 'jaggery'],
    'aerated': ['soft drink', 'pepsi', 'cola', 'soda'],
    'juice': ['fruit juice', 'real juice', 'nectar'],
    'fish': ['seafood', 'prawn', 'shrimp', 'kozhuva', 'sardine'],
    'prawn': ['shrimp', 'fish', 'seafood'],
    'chicken': ['poultry', 'meat', 'chkn', 'broiler'],
    'toy': ['plaything', 'game', 'play set', 'doll', 'vehicle'],
    'doll': ['toy', 'figurine', 'play'],
    'notebook': ['note book', 'exercise book', 'writing book', 'nb'],
    'pen': ['ball pen', 'writing pen', 'gel pen', 'ink pen'],
    'pencil': ['drawing pencil', 'hb pencil', 'graphite'],
    'eraser': ['rubber eraser', 'correction'],
    'umbrella': ['rain umbrella', 'telescopic umbrella', 'umbrla'],
    'pickle': ['achar', 'pickled', 'brined', 'mango pickle'],
    'jam': ['jelly', 'marmalade', 'fruit spread'],
    'ketchup': ['sauce', 'tomato sauce', 'chilli sauce'],
    'salt': ['iodised salt', 'rock salt', 'pink salt', 'namak'],
    'camphor': ['karpoor', 'kapur', 'naphthalene'],
    'match': ['matchbox', 'safety match', 'fire match'],
    'christmas': ['xmas', 'decoration', 'festive', 'x-mas tree'],
}

DOMAIN_PREFIXES = {
    'footwear': ['64'], 'shoe': ['64'], 'sandal': ['64'],
    'slipper': ['64'], 'chappal': ['64'], 'vkc': ['64'],
    'hawai': ['64'], 'flipflop': ['64'],
    'container': ['39'], 'basket': ['39'], 'hanger': ['39'],
    'plastic': ['39'], 'casserole': ['39'], 'laundry': ['39'],
    'dustbin': ['39'], 'bucket': ['39'],
    'stainless': ['73'], 'steel': ['73'],
    'utensil': ['73', '76', '69', '70'],
    'ladle': ['73', '82'], 'spatula': ['73', '82'],
    'strainer': ['73', '82'], 'tongs': ['73', '82'],
    'aluminium': ['76'], 'aluminum': ['76'],
    'glassware': ['70'], 'ceramic': ['69'], 'porcelain': ['69'],
    'cosmetic': ['33'], 'makeup': ['33'], 'skincare': ['33'],
    'skin': ['33'], 'toothpaste': ['33'], 'agarbatti': ['33'],
    'agarbathi': ['33'], 'incense': ['33'], 'perfume': ['33'],
    'deodorant': ['33'], 'fogg': ['33'], 'lipstick': ['33'],
    'fairness': ['33'], 'shampoo': ['33'], 'conditioner': ['33'],
    'soap': ['34', '33'], 'detergent': ['34'], 'phenyl': ['34'],
    'disinfectant': ['34'], 'bleach': ['34'], 'harpic': ['34'],
    'cleaning': ['34'], 'cleaner': ['34'],
    'dishwash': ['34'], 'dishwasher': ['34'],
    'toothbrush': ['96'], 'brush': ['96'], 'pen': ['96'],
    'pencil': ['96'], 'eraser': ['96'], 'sharpener': ['96'],
    'marker': ['96'],
    'toy': ['95'], 'doll': ['95'], 'game': ['95'],
    'christmas': ['95'], 'xmas': ['95'], 'balloon': ['95'],
    'puzzle': ['95'],
    'notebook': ['48'], 'paper': ['48'], 'envelope': ['48'],
    'stationery': ['48', '96'],
    'book': ['48', '49'], 'textbook': ['49'],
    'rice': ['10'], 'basmati': ['10'], 'matta': ['10'],
    'wheat': ['10', '11'], 'oats': ['10', '11'], 'barley': ['10'],
    'atta': ['11'], 'flour': ['11'], 'maida': ['11'],
    'suji': ['11'], 'rava': ['11'], 'poha': ['11'],
    'aval': ['11'], 'puttupodi': ['11'],
    'milk': ['04'], 'ghee': ['04'], 'butter': ['04'],
    'cheese': ['04'], 'paneer': ['04'], 'yogurt': ['04'],
    'curd': ['04'], 'cream': ['04', '33'], 'egg': ['04'],
    'dairy': ['04'],
    'masala': ['09'], 'spice': ['09'], 'turmeric': ['09'],
    'chilli': ['09'], 'pepper': ['09'], 'cardamom': ['09'],
    'cinnamon': ['09'], 'fenugreek': ['09'], 'ginger': ['09'],
    'coriander': ['09'],
    'oil': ['15'], 'sesame': ['15'], 'gingelly': ['15'],
    'sunflower': ['15'], 'castor': ['15'],
    'vanaspati': ['15'], 'palm oil': ['15'],
    'biscuit': ['19'], 'cookie': ['19'], 'wafer': ['19'],
    'chips': ['19'], 'puff': ['19'], 'snack': ['19'],
    'cereal': ['19'], 'popcorn': ['19'], 'noodle': ['19'],
    'pasta': ['19'], 'bread': ['19'],
    'cashew': ['08', '20'], 'cashw': ['08', '20'],
    'chocolate': ['18'], 'cocoa': ['18'],
    'sugar': ['17'], 'jaggery': ['17'], 'candy': ['17'], 'toffee': ['17'],
    'pickle': ['20'], 'jam': ['20'], 'jelly': ['20'], 'preserve': ['20'],
    'ketchup': ['21'], 'sauce': ['21'], 'mayonnaise': ['21'],
    'vinegar': ['21'], 'ice cream': ['21'],
    'aerated': ['22'], 'juice': ['20', '22'],
    'water': ['22'], 'soda': ['22'],
    'fish': ['03'], 'prawn': ['03'], 'seafood': ['03'], 'shrimp': ['03'],
    'chicken': ['02'], 'meat': ['02'],
    'salt': ['25'],
    'camphor': ['29'],
    'match': ['36'], 'matchbox': ['36'],
    'razor': ['82'], 'blade': ['82'], 'knife': ['82'],
    'scissors': ['82'], 'cutter': ['82'],
    'computer': ['84'], 'laptop': ['84'], 'stapler': ['84'],
    'phone': ['85'], 'mobile': ['85'], 'smartphone': ['85'],
    'television': ['85'],
    'bulb': ['94'], 'led': ['94'], 'light': ['94'],
    'umbrella': ['66'],
    'insole': ['64'],
}

CATEGORY_RULES = [
    {'keywords': ['tooth', 'paste', 'toothpaste', 'dentifrice'],   'chapters': ['33']},
    {'keywords': ['toothbrush', 'tbrush'],                          'chapters': ['96']},
    {'keywords': ['note', 'book', 'notebook', 'copybook'],          'chapters': ['48']},
    {'keywords': ['puja', 'pooja', 'thiri', 'wick', 'lamp oil'],    'chapters': ['33']},
    {'keywords': ['agarbatti', 'agarbathi', 'incense', 'sambrani'], 'chapters': ['33']},
    {'keywords': ['cleaning', 'cleaner', 'detergent', 'phenyl', 'disinfectant', 'harpic'], 'chapters': ['34']},
    {'keywords': ['cosmetic', 'makeup', 'skincare', 'foundation', 'kajal', 'eyeshadow'], 'chapters': ['33']},
    {'keywords': ['soap', 'toilet soap'],                           'chapters': ['34', '33']},
    {'keywords': ['shampoo', 'conditioner', 'hair wash'],           'chapters': ['33']},
    {'keywords': ['phone', 'mobile', 'smartphone'],                 'chapters': ['85']},
    {'keywords': ['television', 'tv'],                              'chapters': ['85']},
    {'keywords': ['computer', 'laptop'],                            'chapters': ['84']},
    {'keywords': ['fridge', 'refrigerator'],                        'chapters': ['84']},
    {'keywords': ['vkc', 'footwear', 'sandal', 'slipper', 'chappal', 'shoe', 'hawai'], 'chapters': ['64']},
    {'keywords': ['toy', 'doll', 'puzzle', 'balloon', 'xmas', 'christmas'], 'chapters': ['95']},
    {'keywords': ['pen', 'pencil', 'eraser', 'marker', 'highlighter'], 'chapters': ['96']},
    {'keywords': ['umbrella', 'umbrla'],                            'chapters': ['66']},
    {'keywords': ['match', 'matchbox', 'safety match'],             'chapters': ['36']},
    {'keywords': ['camphor', 'karpoor'],                            'chapters': ['29']},
    {'keywords': ['oil'],                                           'chapters': ['15']},
    {'keywords': ['food', 'beverage', 'drink'],                     'chapters': ['04', '19', '20', '21', '22']},
    {'keywords': ['clothing', 'garment', 'fabric', 'pants', 'shirt', 'palazzo'], 'chapters': ['61', '62', '63']},
    {'keywords': ['furniture', 'sofa', 'chair', 'table'],          'chapters': ['94']},
    {'keywords': ['steel', 'stainless'],                            'chapters': ['73']},
    {'keywords': ['aluminium', 'aluminum'],                         'chapters': ['76']},
    {'keywords': ['plastic', 'container', 'basket', 'hanger'],     'chapters': ['39']},
    {'keywords': ['glass', 'ceramic', 'porcelain'],                 'chapters': ['70', '69']},
    {'keywords': ['rice', 'basmati', 'matta'],                      'chapters': ['10']},
    {'keywords': ['atta', 'flour', 'maida', 'suji', 'rava', 'puttupodi', 'aval', 'poha'], 'chapters': ['11']},
    {'keywords': ['spice', 'masala', 'turmeric', 'chilli', 'pepper', 'cardamom'], 'chapters': ['09']},
    {'keywords': ['chocolate', 'cocoa', 'choco'],                   'chapters': ['18']},
    {'keywords': ['biscuit', 'cookie', 'wafer', 'chips', 'puff', 'snack', 'cereal', 'popcorn', 'cooki', 'cookis'], 'chapters': ['19']},
    {'keywords': ['sugar', 'jaggery', 'candy', 'toffee'],           'chapters': ['17']},
    {'keywords': ['dairy', 'milk', 'ghee', 'butter', 'cheese', 'paneer', 'curd', 'yogurt'], 'chapters': ['04']},
    {'keywords': ['fish', 'prawn', 'seafood', 'shrimp'],            'chapters': ['03']},
    {'keywords': ['chicken', 'meat', 'poultry'],                    'chapters': ['02']},
    {'keywords': ['knife', 'scissors', 'razor', 'blade', 'cutter'], 'chapters': ['82']},
    {'keywords': ['salt', 'iodised salt'],                          'chapters': ['25']},
    {'keywords': ['pickle', 'achar'],                               'chapters': ['20']},
    {'keywords': ['jam', 'jelly', 'marmalade'],                     'chapters': ['20']},
    {'keywords': ['ketchup', 'sauce', 'ice cream', 'supplement'],   'chapters': ['21']},
    {'keywords': ['juice', 'aerated', 'soft drink', 'water', 'soda'], 'chapters': ['22']},
    {'keywords': ['cashew', 'cashw', 'kaju'],                       'chapters': ['08', '20']},
]

# ── Helper functions ───────────────────────────────────────────────────────────

def expand_fmcg_abbreviations(text: str) -> str:
    words = text.split()
    expanded_words = []
    for word in words:
        lower_word = word.lower()
        if lower_word in FMCG_ABBREVIATIONS:
            expanded_words.append(FMCG_ABBREVIATIONS[lower_word])
        else:
            expanded_words.append(lower_word)
    return ' '.join(expanded_words)


def _extract_alpha_tokens(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r'\b\d+\s*(ml|g|gm|kg|l|ltr|mg|oz|lb|pc|pcs|nos)\b', ' ', text)
    text = re.sub(r'\b\d+\b', ' ', text)
    return re.findall(r'[a-z]{2,}', text)


def tokenize(text: str, *, include_brands: bool = False) -> list[str]:
    tokens = _extract_alpha_tokens(text)
    return [
        t for t in tokens
        if t not in STOPWORDS and len(t) >= 2 and (include_brands or t not in BRANDS)
    ]


def split_query_fields(text: str) -> dict[str, list[str]]:
    expanded = expand_fmcg_abbreviations(text)
    raw_tokens = _extract_alpha_tokens(expanded)
    brand_tokens = [t for t in raw_tokens if t in BRANDS]
    product_tokens = tokenize(expanded)
    domain_tokens = [t for t in product_tokens if t in DOMAIN_PREFIXES]
    return {
        "brand_tokens": list(dict.fromkeys(brand_tokens)),
        "product_tokens": list(dict.fromkeys(product_tokens)),
        "domain_tokens": list(dict.fromkeys(domain_tokens)),
        "all_tokens": list(dict.fromkeys(tokenize(expanded, include_brands=True))),
    }


def detect_category_restrictions(tokens: list[str]) -> list[str]:
    for rule in CATEGORY_RULES:
        if any(keyword in tokens for keyword in rule['keywords']):
            return rule['chapters']
    return []


def build_hsn_prefix_clause(tokens: list[str]) -> tuple[str, dict]:
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
    query_terms: list[str] = []
    for token in tokens:
        variants = [token] + SYNONYMS.get(token, [])
        single_word_variants = [v for v in variants if ' ' not in v]
        if len(single_word_variants) > 1:
            query_terms.append("(" + " | ".join(single_word_variants) + ")")
        else:
            query_terms.append(token)
    return query_terms


def compute_weighted_jaccard(tokens: list[str], desc_tokens: set[str]) -> float:
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


def _build_candidate_lexical_index(
    query: str,
    rows,
    *,
    description_attr: str = "description",
    category_attr: str = "category",
):
    query_fields = split_query_fields(query)
    documents = []
    token_docs: dict[str, set[int]] = {}
    for idx, row in enumerate(rows):
        description = str(getattr(row, description_attr, "") or "")
        category = str(getattr(row, category_attr, "") or "")
        desc_expanded = expand_fmcg_abbreviations(description)
        raw_desc_tokens = _extract_alpha_tokens(desc_expanded)
        brand_tokens = set(t for t in raw_desc_tokens if t in BRANDS)
        desc_tokens = set(tokenize(desc_expanded))
        category_tokens = set(tokenize(category))
        doc_tokens = desc_tokens | category_tokens | brand_tokens
        documents.append({
            "brand_tokens": brand_tokens,
            "desc_tokens": desc_tokens,
            "category_tokens": category_tokens,
            "doc_tokens": doc_tokens,
            "text_lower": description.lower(),
        })
        for token in doc_tokens:
            token_docs.setdefault(token, set()).add(idx)
    return {
        "query_fields": query_fields,
        "documents": documents,
        "token_docs": token_docs,
        "doc_count": len(documents),
    }


def _token_rarity_weight(token: str, lexical_index) -> float:
    doc_count = max(int(lexical_index["doc_count"]), 1)
    df = len(lexical_index["token_docs"].get(token, ()))
    return math.log((doc_count + 1.0) / (df + 0.5)) + 1.0


def compute_inverted_index_score(
    query: str,
    row,
    lexical_index,
    *,
    doc_idx: int,
    base_db_score: float = 0.0,
) -> float:
    query_fields = lexical_index["query_fields"]
    document = lexical_index["documents"][doc_idx]
    query_brand_tokens = query_fields["brand_tokens"]
    query_product_tokens = query_fields["product_tokens"]
    query_domain_tokens = set(query_fields["domain_tokens"])

    if not query_product_tokens and not query_brand_tokens:
        return max(0.0, min(base_db_score, 1.0))

    score = 0.0
    weight_total = 0.0

    for token in query_product_tokens:
        rarity = _token_rarity_weight(token, lexical_index)
        token_weight = rarity + (0.25 if len(token) >= 5 else 0.0)
        if token in query_domain_tokens:
            token_weight += 0.35
        if token in document["desc_tokens"]:
            score += token_weight
        elif token in document["category_tokens"]:
            score += token_weight * 0.75
        else:
            for synonym in SYNONYMS.get(token, []):
                if synonym in document["doc_tokens"]:
                    score += token_weight * 0.55
                    break
        weight_total += token_weight

    for brand_token in query_brand_tokens:
        brand_weight = 2.8 + _token_rarity_weight(brand_token, lexical_index)
        if brand_token in document["brand_tokens"]:
            score += brand_weight * 1.25
        elif brand_token in document["desc_tokens"]:
            score += brand_weight * 0.9
        weight_total += brand_weight

    lexical_score = score / weight_total if weight_total else 0.0

    if query_brand_tokens and document["brand_tokens"] and not (
        set(query_brand_tokens) & document["brand_tokens"]
    ):
        lexical_score -= 0.16

    ordered_product_tokens = [t for t in query_product_tokens if len(t) >= 3]
    if ordered_product_tokens:
        phrase = " ".join(ordered_product_tokens[:4])
        if phrase and phrase in document["text_lower"]:
            lexical_score += 0.12
        elif all(t in document["doc_tokens"] for t in ordered_product_tokens[:3]):
            lexical_score += 0.06

    restriction_tokens = query_fields["all_tokens"] or query_product_tokens
    preferred_prefixes = detect_category_restrictions(restriction_tokens)
    row_hsn = normalize_hsn(getattr(row, "hsn_code", "") or "")
    if preferred_prefixes and row_hsn:
        if any(row_hsn.startswith(prefix) for prefix in preferred_prefixes):
            lexical_score += 0.08
        else:
            lexical_score -= 0.06

    final_score = lexical_score * 0.74 + max(base_db_score, 0.0) * 0.26
    return max(0.0, min(final_score, 1.0))


# ── Schema probe (cached) ──────────────────────────────────────────────────────
_VP_HAS_NO_SIZE_COL: Optional[bool] = None

async def _probe_vp_schema(db: AsyncSession) -> bool:
    global _VP_HAS_NO_SIZE_COL
    if _VP_HAS_NO_SIZE_COL is not None:
        return _VP_HAS_NO_SIZE_COL
    try:
        await db.execute(text("SELECT description_no_size FROM verified_products LIMIT 0"))
        _VP_HAS_NO_SIZE_COL = True
    except Exception:
        _VP_HAS_NO_SIZE_COL = False
        log.warning(
            "verified_products.description_no_size column missing — "
            "Pass 0B/0C disabled. Run: ALTER TABLE verified_products "
            "ADD COLUMN description_no_size VARCHAR(500); to enable."
        )
    return _VP_HAS_NO_SIZE_COL


def _majority_hsn(rows, min_freq: int = 1):
    if not rows:
        return None, None, None, 0, []
    import collections as _col
    hsn_groups = _col.defaultdict(list)
    for r in rows:
        hsn_groups[r.hsn_code].append(r)
    ranked = sorted(
        hsn_groups.items(),
        key=lambda kv: (-len(kv[1]), min(len(x.description) for x in kv[1])),
    )
    best_hsn, best_rows = ranked[0]
    best_row = min(best_rows, key=lambda r: len(r.description))
    freq = len(best_rows)
    alts = []
    for alt_hsn, alt_rows in ranked[1:4]:
        alt_row = min(alt_rows, key=lambda r: len(r.description))
        alts.append({
            "hsn_code": normalize_hsn(alt_hsn),
            "description": alt_row.description,
            "gst_rate": float(alt_row.gst_rate or 0),
            "confidence": round(len(alt_rows) / max(freq, 1) * 0.7, 3),
        })
    return best_hsn, best_row.gst_rate, best_row.description, freq, alts


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 & 4 HELPERS — Intent scoring + confidence calibration
# ══════════════════════════════════════════════════════════════════════════════

INTENT_BOOSTS = {
    # (query_keyword, match_keyword_in_description): delta
    ("jam", "jam"):             +0.18,
    ("jam", "jelly"):           +0.08,
    ("jam", "marmalade"):       +0.06,
    ("jam", "cocktail"):        -0.22,
    ("jam", "nectar"):          -0.15,
    ("jam", "preserve"):        +0.04,
    ("oil", "oil"):             +0.10,
    ("puja", "puja"):           +0.22,
    ("puja", "agarbatti"):      -0.12,
    ("puja", "oil"):            +0.12,
    ("harpic", "toilet"):       +0.15,
    ("harpic", "cleaner"):      +0.12,
    ("harpic", "disinfect"):    +0.10,
    ("sesame", "sesame"):       +0.10,
    ("cashew", "cashew"):       +0.15,
    ("cashew", "cashw"):        +0.15,
    ("cooki", "cooki"):         +0.12,
    ("cooki", "cookie"):        +0.12,
    ("cookie", "cooki"):        +0.12,
    ("cookie", "cookie"):       +0.12,
    ("cookie", "biscuit"):      +0.06,
    ("biscuit", "biscuit"):     +0.12,
    ("horlicks", "horlicks"):   +0.22,
    ("womens", "womens"):       +0.18,
    ("toothpaste", "tooth"):    +0.15,
    ("shampoo", "shampoo"):     +0.15,
    ("detergent", "detergent"): +0.12,
    ("rice", "rice"):           +0.12,
    ("flour", "flour"):         +0.12,
    ("atta", "atta"):           +0.15,
    ("turmeric", "turmeric"):   +0.15,
    ("salt", "salt"):           +0.15,
    ("ghee", "ghee"):           +0.15,
    ("fruit", "fruit"):         +0.08,
    ("fruit", "cocktail"):      -0.18,
}


def _compute_intent_bonus(query_tokens: list[str], description: str) -> float:
    """Layer 3: Boost/penalize based on keyword intent vs matched description."""
    desc_lower = description.lower()
    bonus = 0.0
    for qt in query_tokens:
        qt_lower = qt.lower()
        for (qk, mk), delta in INTENT_BOOSTS.items():
            if qt_lower == qk and mk in desc_lower:
                bonus += delta
    return max(-0.35, min(0.35, bonus))


def _calibrate_confidence(
    conf: float,
    query_words: list[str],
    description: str,
    *,
    max_conf: float = 1.0,
) -> float:
    """
    Layer 4: Boost confidence when query words are a subset of matched description.
    'HORLICKS WOMENS' found in 'HORLICKS WOMENS CHOCO PET 400G' → +0.12
    """
    if not query_words:
        return conf
    desc_upper = description.upper()
    sig_words = [w for w in query_words if len(w) >= 3]
    if not sig_words:
        return conf
    matched = sum(1 for w in sig_words if w in desc_upper)
    ratio = matched / len(sig_words)
    if ratio >= 1.0:
        conf = min(max_conf, conf + 0.12)
    elif ratio >= 0.7:
        conf = min(max_conf, conf + 0.06)
    return round(conf, 3)


# ══════════════════════════════════════════════════════════════════════════════
# CORE MATCHING ENGINE v3 — 4-layer fix applied
# ══════════════════════════════════════════════════════════════════════════════
async def _match_one(query: str, db: AsyncSession) -> HSNBatchResult:
    """
    Multi-pass HSN matching (v3 — 4-layer fix).

    Layer 1: Early abbreviation expansion before ALL passes.
    Layer 2: Passes 0D-0F use description_normalized (always populated) as primary.
    Layer 3: Intent-based scoring in FTS and verified-product passes.
    Layer 4: Confidence calibration boost when query words ⊆ match description.

    Pass 0A : verified_products exact uppercase                     → conf 1.00
    Pass 0B : verified_products size-stripped exact                 → conf 0.95
    Pass 0C : verified_products pg_trgm on no_size (≥0.60)         → conf sim-based
    Pass 0D : verified_products prefix on description_normalized    → conf 0.62-0.90
    Pass 0E : verified_products ALL words in description_normalized → conf 0.55-0.88
    Pass 0E2: top-60% words in description_normalized               → conf 0.44-0.78
    Pass 0F : ANY keyword (+ synonyms) in description_normalized    → conf 0.30-0.72
    Pass 1  : exact numeric HSN code
    Pass 2  : full-text search (FTS) via hsn_search
    Pass 3  : trigram on hsn_search.normalized_description
    Pass 4  : ILIKE keyword fallback on hsn_codes
    """
    import re as _re

    q_stripped = query.strip()
    q_upper = q_stripped.upper()

    # ── Layer 1: Expand abbreviations early (used in ALL passes) ──────────────
    q_expanded = expand_fmcg_abbreviations(q_stripped)
    q_expanded_upper = q_expanded.upper()

    q_ns          = _strip_sizes(q_stripped)   # size-stripped UPPERCASE (original)
    q_ns_expanded = _strip_sizes(q_expanded)   # size-stripped UPPERCASE (expanded)

    # Extract meaningful words (≥3 chars) from both forms
    q_words     = [w for w in _re.findall(r'[A-Z]{2,}', q_ns) if len(w) >= 3]
    q_words_exp = [w for w in _re.findall(r'[A-Z]{2,}', q_ns_expanded.upper()) if len(w) >= 3]
    # Combined deduped word list for searching
    q_all_words = list(dict.fromkeys(q_words + q_words_exp))

    vp_has_col = await _probe_vp_schema(db)

    # ── Shared builder: majority-vote → HSNBatchResult ────────────────────────
    def _build_vp_result(method: str, rows, base_conf: float, max_conf: float):
        best_hsn, best_gst, best_desc, freq, alts = _majority_hsn(rows)
        if not best_hsn:
            return None
        conf = round(min(max_conf, base_conf + freq * 0.04), 3)
        # Layer 4: boost when query words subset of matched description
        conf = _calibrate_confidence(conf, q_all_words, best_desc, max_conf=max_conf)
        gst_float = float(_re.sub(r'[^0-9.]', '', str(best_gst or 0)) or 0)
        label = "high" if conf >= 0.80 else ("medium" if conf >= 0.55 else "low")
        return HSNBatchResult(
            query=query,
            hsn_code=normalize_hsn(best_hsn),
            description=best_desc,
            gst_rate=gst_float,
            confidence=conf,
            confidence_label=label,
            match_method=method,
            alternatives=alts,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # PASS 0A — Exact normalized match (try original + expanded form)
    # ══════════════════════════════════════════════════════════════════════════
    for exact_q in list(dict.fromkeys([q_upper, q_expanded_upper])):
        try:
            res = await db.execute(
                text("""
                    SELECT vp.hsn_code, vp.gst_rate, vp.description
                    FROM verified_products vp
                    WHERE vp.description_normalized = :q
                    LIMIT 1
                """),
                {"q": exact_q},
            )
            row = res.fetchone()
            if row:
                conf = _calibrate_confidence(1.0, q_all_words, row.description, max_conf=1.0)
                gst_float = float(_re.sub(r'[^0-9.]', '', str(row.gst_rate or 0)) or 0)
                return HSNBatchResult(
                    query=query,
                    hsn_code=normalize_hsn(row.hsn_code),
                    description=row.description,
                    gst_rate=gst_float,
                    confidence=conf,
                    confidence_label="high",
                    match_method="verified_exact",
                )
        except Exception as e:
            log.warning("pass0A.error query=%s error=%s", q_stripped[:50], str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # PASS 0B — Size-stripped exact match
    # ══════════════════════════════════════════════════════════════════════════
    if vp_has_col:
        for ns_q in list(dict.fromkeys([q_ns, q_ns_expanded])):
            if not ns_q:
                continue
            try:
                res = await db.execute(
                    text("""
                        SELECT vp.hsn_code, vp.gst_rate, vp.description
                        FROM verified_products vp
                        WHERE vp.description_no_size = :q
                        ORDER BY vp.id
                        LIMIT 1
                    """),
                    {"q": ns_q},
                )
                row = res.fetchone()
                if row:
                    conf = _calibrate_confidence(0.95, q_all_words, row.description, max_conf=1.0)
                    gst_float = float(_re.sub(r'[^0-9.]', '', str(row.gst_rate or 0)) or 0)
                    return HSNBatchResult(
                        query=query,
                        hsn_code=normalize_hsn(row.hsn_code),
                        description=row.description,
                        gst_rate=gst_float,
                        confidence=conf,
                        confidence_label="high",
                        match_method="verified_no_size",
                    )
            except Exception as e:
                log.warning("pass0B.error query=%s error=%s", q_stripped[:50], str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # PASS 0C — Trigram on description_no_size (≥0.60)
    # ══════════════════════════════════════════════════════════════════════════
    if vp_has_col:
        for ns_q in list(dict.fromkeys([q_ns, q_ns_expanded])):
            if not ns_q:
                continue
            try:
                res = await db.execute(
                    text("""
                        SELECT vp.hsn_code, vp.gst_rate, vp.description,
                               similarity(vp.description_no_size, :q) AS sim
                        FROM verified_products vp
                        WHERE vp.description_no_size % :q
                        ORDER BY sim DESC
                        LIMIT 1
                    """),
                    {"q": ns_q},
                )
                row = res.fetchone()
                if row and float(row.sim) >= 0.60:
                    sim = float(row.sim)
                    conf = _calibrate_confidence(round(sim, 3), q_all_words, row.description, max_conf=1.0)
                    gst_float = float(_re.sub(r'[^0-9.]', '', str(row.gst_rate or 0)) or 0)
                    return HSNBatchResult(
                        query=query,
                        hsn_code=normalize_hsn(row.hsn_code),
                        description=row.description,
                        gst_rate=gst_float,
                        confidence=conf,
                        confidence_label="high" if conf >= 0.80 else "medium",
                        match_method="verified_trigram",
                    )
            except Exception as e:
                log.warning("pass0C.error query=%s error=%s", q_stripped[:50], str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # LAYER 2 FIX: Passes 0D–0F now search description_normalized (PRIMARY)
    # This fixes SESAME/HARPIC/PUJA OIL/FRUIT JAM returning "none" because
    # they previously only searched description_no_size which may be NULL.
    # ══════════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════════
    # PASS 0D — PREFIX search on description_normalized
    # "HARPIC"  → "HARPIC DISINFTNT BTRM CLNR FLORL 500ML"
    # "HORLICK" → "HORLICKS WOMENS CHOCO PET 400G"
    # Tries: original prefix, expanded prefix
    # ══════════════════════════════════════════════════════════════════════════
    for prefix_q in list(dict.fromkeys([q_upper, q_expanded_upper])):
        if not prefix_q or len(prefix_q) < 3:
            continue
        try:
            res = await db.execute(
                text("""
                    SELECT vp.hsn_code, vp.gst_rate, vp.description
                    FROM verified_products vp
                    WHERE vp.description_normalized LIKE :prefix
                    ORDER BY LENGTH(vp.description_normalized) ASC
                    LIMIT 20
                """),
                {"prefix": prefix_q + "%"},
            )
            rows = res.fetchall()
            if rows:
                result = _build_vp_result("verified_prefix", rows, base_conf=0.62, max_conf=0.90)
                if result and result.confidence >= 0.52:
                    return result
        except Exception as e:
            log.warning("pass0D.error query=%s error=%s", q_stripped[:50], str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # PASS 0E — ALL query words in description_normalized
    # Uses q_all_words (original + Layer 1 expanded) for better matching.
    # "FRUIT JAM 350g" → words [FRUIT,JAM] → many jam entries → 20079990
    # "HORLICKS WOMENS" → [HORLICKS,WOMENS] → 19019090
    # "PURE PUJA OIL"  → [PURE,PUJA,OIL] → 15180040
    # "CASHW COOKI"    → [CASHW,COOKI,CASHEW,COOKIE] → 19053100
    # ══════════════════════════════════════════════════════════════════════════
    if len(q_all_words) >= 2:
        # Try different word sets: original, expanded, combined
        word_sets_to_try = []
        seen_keys: set = set()
        for ws in [q_words, q_words_exp, q_all_words]:
            if len(ws) >= 2:
                key = tuple(sorted(ws))
                if key not in seen_keys:
                    seen_keys.add(key)
                    word_sets_to_try.append(ws)

        for words_to_use in word_sets_to_try:
            try:
                where_parts = " AND ".join(
                    f"vp.description_normalized LIKE :w{i}" for i in range(len(words_to_use))
                )
                params = {f"w{i}": f"%{w}%" for i, w in enumerate(words_to_use)}
                res = await db.execute(
                    text(f"""
                        SELECT vp.hsn_code, vp.gst_rate, vp.description
                        FROM verified_products vp
                        WHERE {where_parts}
                        LIMIT 30
                    """),
                    params,
                )
                rows = res.fetchall()
                if rows:
                    result = _build_vp_result(
                        "verified_allwords", rows, base_conf=0.55, max_conf=0.88
                    )
                    if result and result.confidence >= 0.48:
                        # Layer 3: apply intent bonus
                        tokens_for_intent = tokenize(q_expanded)
                        intent = _compute_intent_bonus(tokens_for_intent, result.description)
                        if intent < -0.12:
                            continue  # wrong category match, try next word set
                        result.confidence = round(
                            min(0.88, result.confidence + max(0.0, intent)), 3
                        )
                        result.confidence_label = (
                            "high" if result.confidence >= 0.80 else
                            "medium" if result.confidence >= 0.55 else "low"
                        )
                        return result
            except Exception as e:
                log.warning("pass0E.error query=%s error=%s", q_stripped[:50], str(e))

        # Also try description_no_size when available (secondary)
        if vp_has_col and len(q_words) >= 2:
            try:
                where_parts = " AND ".join(
                    f"vp.description_no_size LIKE :ws{i}" for i in range(len(q_words))
                )
                params = {f"ws{i}": f"%{w}%" for i, w in enumerate(q_words)}
                res = await db.execute(
                    text(f"""
                        SELECT vp.hsn_code, vp.gst_rate, vp.description
                        FROM verified_products vp
                        WHERE {where_parts}
                        LIMIT 30
                    """),
                    params,
                )
                rows = res.fetchall()
                if rows:
                    result = _build_vp_result(
                        "verified_allwords_ns", rows, base_conf=0.55, max_conf=0.88
                    )
                    if result and result.confidence >= 0.48:
                        return result
            except Exception as e:
                log.warning("pass0E_ns.error query=%s error=%s", q_stripped[:50], str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # PASS 0E2 — Top-60% of words on description_normalized
    # ══════════════════════════════════════════════════════════════════════════
    if len(q_all_words) >= 2:
        try:
            needed = max(1, round(len(q_all_words) * 0.60))
            top_words = sorted(q_all_words, key=len, reverse=True)[:needed]
            where_parts = " AND ".join(
                f"vp.description_normalized LIKE :rw{i}" for i in range(len(top_words))
            )
            params = {f"rw{i}": f"%{w}%" for i, w in enumerate(top_words)}
            res = await db.execute(
                text(f"""
                    SELECT vp.hsn_code, vp.gst_rate, vp.description
                    FROM verified_products vp
                    WHERE {where_parts}
                    LIMIT 30
                """),
                params,
            )
            rows = res.fetchall()
            if rows:
                result = _build_vp_result(
                    "verified_partial", rows, base_conf=0.44, max_conf=0.78
                )
                if result and result.confidence >= 0.42:
                    tokens_for_intent = tokenize(q_expanded)
                    intent = _compute_intent_bonus(tokens_for_intent, result.description)
                    if intent >= -0.08:
                        result.confidence = round(
                            min(0.78, result.confidence + max(0.0, intent)), 3
                        )
                        result.confidence_label = (
                            "high" if result.confidence >= 0.80 else
                            "medium" if result.confidence >= 0.55 else "low"
                        )
                        return result
        except Exception as e:
            log.warning("pass0E2.error query=%s error=%s", q_stripped[:50], str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # PASS 0F — Single keyword (+ synonyms) on description_normalized
    # Layer 2 FIX: Uses description_normalized (always exists), not just no_size.
    # "SESAME"  → all sesame entries → majority HSN
    # "HARPIC"  → all harpic entries → majority HSN
    # Also expands: "CASHW" tries "CASHEW" via synonyms too
    # ══════════════════════════════════════════════════════════════════════════
    if q_all_words:
        best_word_orig = max(q_words, key=len) if q_words else ""
        best_word_exp  = max(q_words_exp, key=len) if q_words_exp else ""
        # Include synonyms of the best keyword for broader matching
        synonym_kws = [
            syn.upper() for syn in SYNONYMS.get(best_word_orig.lower(), [])
            if len(syn) >= 3 and ' ' not in syn
        ][:3]
        candidate_keywords = list(dict.fromkeys(
            [w for w in [best_word_orig, best_word_exp] if w] + synonym_kws
        ))

        for kw in candidate_keywords:
            if not kw or len(kw) < 3:
                continue
            try:
                res = await db.execute(
                    text("""
                        SELECT vp.hsn_code, vp.gst_rate, vp.description
                        FROM verified_products vp
                        WHERE vp.description_normalized LIKE :kw
                        LIMIT 50
                    """),
                    {"kw": f"%{kw}%"},
                )
                rows = res.fetchall()
                if rows:
                    result = _build_vp_result(
                        "verified_keyword", rows, base_conf=0.30, max_conf=0.72
                    )
                    if result and result.confidence >= 0.27:
                        tokens_for_intent = tokenize(q_expanded)
                        intent = _compute_intent_bonus(tokens_for_intent, result.description)
                        result.confidence = round(
                            min(0.72, result.confidence + max(0.0, intent)), 3
                        )
                        result.confidence_label = (
                            "high" if result.confidence >= 0.80 else
                            "medium" if result.confidence >= 0.55 else "low"
                        )
                        return result
            except Exception as e:
                log.warning("pass0F.error kw=%s error=%s", kw, str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # PASS 1 — Exact HSN code (numeric input)
    # ══════════════════════════════════════════════════════════════════════════
    if re.match(r'^\d{4,8}$', q_stripped):
        try:
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
                    hsn_code=normalize_hsn(row.hsn_code),
                    description=row.description,
                    gst_rate=float(row.gst_rate or 0),
                    confidence=1.0,
                    confidence_label="high",
                    match_method="exact_code",
                )
        except Exception as e:
            log.warning("pass1.error query=%s error=%s", q_stripped[:50], str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # PASSES 2–4 — FTS / trigram / ILIKE on hsn_codes table
    # Layer 1: tokenize q_expanded (not q_stripped) for better FTS
    # Layer 3: intent bonus applied to each FTS result
    # ══════════════════════════════════════════════════════════════════════════
    tokens = tokenize(q_expanded)   # Layer 1: use expanded form
    if not tokens:
        return HSNBatchResult(query=query, match_method="none")

    domain_clause, domain_params = build_hsn_prefix_clause(tokens)

    # Pass 2: full-text search (AND then OR fallback)
    rows_fts = []
    try:
        ts_query_terms = build_tsquery_terms(tokens)
        ts_and = " & ".join(ts_query_terms[:8])
        res = await db.execute(
            text("""
                SELECT h.hsn_code, h.description, h.gst_rate, h.category,
                       ts_rank(s.search_vector, query) AS rank
                FROM hsn_search s
                JOIN hsn_codes h ON h.hsn_code = s.hsn_code
                CROSS JOIN to_tsquery('english', :q) query
                WHERE s.search_vector @@ query
                  AND h.is_active = TRUE""" + domain_clause + """
                ORDER BY rank DESC
                LIMIT 15
            """),
            {"q": ts_and, **domain_params},
        )
        rows_fts = res.fetchall()
    except Exception:
        rows_fts = []

    if not rows_fts and len(tokens) > 1:
        try:
            ts_or = " | ".join(ts_query_terms[:8])
            res = await db.execute(
                text("""
                    SELECT h.hsn_code, h.description, h.gst_rate, h.category,
                       ts_rank(s.search_vector, query) AS rank
                    FROM hsn_search s
                    JOIN hsn_codes h ON h.hsn_code = s.hsn_code
                    CROSS JOIN to_tsquery('english', :q) query
                    WHERE s.search_vector @@ query
                      AND h.is_active = TRUE""" + domain_clause + """
                    ORDER BY rank DESC
                    LIMIT 15
                """),
                {"q": ts_or, **domain_params},
            )
            rows_fts = res.fetchall()
        except Exception:
            rows_fts = []

    if rows_fts:
        best = None
        best_score = 0.0
        alts = []
        lexical_index = _build_candidate_lexical_index(q_expanded, rows_fts)
        for idx, r in enumerate(rows_fts):
            desc_tokens = set(tokenize(r.description))
            if not desc_tokens:
                continue
            jaccard = compute_weighted_jaccard(tokens, desc_tokens)
            fts_score = min(float(r.rank) * 2.5, 0.4)
            db_score = min(jaccard * 0.45 + fts_score, 1.0)
            final_score = compute_inverted_index_score(
                q_expanded, r, lexical_index, doc_idx=idx, base_db_score=db_score,
            )
            # Layer 3: apply intent bonus
            intent = _compute_intent_bonus(tokens, r.description)
            final_score = max(0.0, min(1.0, final_score + intent))

            entry = {
                "hsn_code": normalize_hsn(r.hsn_code),
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

    # Pass 3: trigram on hsn_search
    try:
        trgm_query = " ".join(tokens[:6])
        res = await db.execute(
            text("""
                SELECT h.hsn_code, h.description, h.gst_rate, h.category,
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
        lexical_index = _build_candidate_lexical_index(q_expanded, rows_trgm)
        ranked_trgm = []
        for idx, r in enumerate(rows_trgm):
            sim_score = min(float(r.sim), 1.0)
            final_score = compute_inverted_index_score(
                q_expanded, r, lexical_index, doc_idx=idx, base_db_score=sim_score,
            )
            # Layer 3: intent bonus
            intent = _compute_intent_bonus(tokens, r.description)
            final_score = max(0.0, min(1.0, final_score + intent))
            ranked_trgm.append((final_score, r))
        ranked_trgm.sort(key=lambda item: item[0], reverse=True)
        best_score, best = ranked_trgm[0]
        best_base_score = min(float(best.sim), 1.0)
        alts = [
            {
                "hsn_code": normalize_hsn(r.hsn_code),
                "description": r.description,
                "gst_rate": float(r.gst_rate or 0),
                "confidence": round(score, 3),
            }
            for score, r in ranked_trgm[1:4]
        ]
        if best_score > 0.15:
            label = "high" if best_base_score >= 0.60 else ("medium" if best_base_score >= 0.30 else "low")
            return HSNBatchResult(
                query=query,
                hsn_code=normalize_hsn(best.hsn_code),
                description=best.description,
                gst_rate=float(best.gst_rate or 0),
                confidence=round(best_score, 3),
                confidence_label=label,
                match_method="trigram",
                alternatives=alts,
            )

    # Pass 4: ILIKE keyword fallback on hsn_codes
    candidates: dict = {}
    for token in tokens[:4]:
        if len(token) < 3:
            continue
        try:
            res = await db.execute(
                text("""
                    SELECT h.hsn_code, h.description, h.gst_rate, h.category
                    FROM hsn_codes h
                    WHERE h.description ILIKE :pat AND h.is_active = TRUE
                    """ + domain_clause + """
                    LIMIT 20
                """),
                {"pat": f"%{token}%", **domain_params},
            )
            for r in res.fetchall():
                key = normalize_hsn(r.hsn_code)
                if key not in candidates:
                    candidates[key] = {
                        "hsn_code":    key,
                        "description": r.description,
                        "gst_rate":    float(r.gst_rate or 0),
                        "category":    r.category,
                        "hits":        0,
                    }
                candidates[key]["hits"] += 1
        except Exception:
            pass

    if candidates:
        candidate_rows = []
        for candidate in candidates.values():
            candidate_rows.append(
                type("CandidateRow", (), {
                    "hsn_code":    candidate["hsn_code"],
                    "description": candidate["description"],
                    "gst_rate":    candidate["gst_rate"],
                    "category":    candidate.get("category", ""),
                })()
            )
        lexical_index = _build_candidate_lexical_index(q_expanded, candidate_rows)
        total_tokens = max(len(tokens), 1)
        scored = sorted(
            [
                (
                    compute_inverted_index_score(
                        q_expanded, row, lexical_index, doc_idx=idx,
                        base_db_score=candidates[row.hsn_code]["hits"] / total_tokens,
                    ),
                    candidates[row.hsn_code],
                )
                for idx, row in enumerate(candidate_rows)
            ],
            key=lambda x: x[0],
            reverse=True,
        )
        top_score, top_c = scored[0]
        if top_score > 0.1:
            label = "high" if top_score >= 0.65 else ("medium" if top_score >= 0.35 else "low")
            alts = [
                {
                    "hsn_code":    c["hsn_code"],
                    "description": c["description"],
                    "gst_rate":    c["gst_rate"],
                    "confidence":  round(s, 3),
                }
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
        # Ensure description_no_size column exists in verified_products
        try:
            await conn.execute(text("""
                ALTER TABLE verified_products
                ADD COLUMN IF NOT EXISTS description_no_size VARCHAR(500)
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_verified_no_size
                ON verified_products (description_no_size)
            """))
        except Exception:
            pass  # Column already exists or table doesn't exist yet