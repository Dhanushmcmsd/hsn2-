from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy import select, String, Float, Integer, Text, Boolean, DateTime, Numeric, Date, text
from pydantic import BaseModel, Field, field_validator
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional
import os, json, re, uuid

# ── Config ───────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./local.db")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "change-me")
JWT_SECRET = os.environ.get("JWT_SECRET", os.environ.get("SECRET_KEY", "change-me"))
ALGORITHM = "HS256"
REDIS_URL = os.environ.get("REDIS_URL", os.environ.get("UPSTASH_REDIS_URL", ""))

if DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# ── DB setup ─────────────────────────────────────────────────────────────────
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
    id:                  Mapped[str]            = mapped_column(String(36), primary_key=True)
    hsn_code:            Mapped[str]            = mapped_column(String(8), index=True)
    hsn_chapter:         Mapped[Optional[str]]  = mapped_column(String(2))
    hsn_heading:         Mapped[Optional[str]]  = mapped_column(String(4))
    hsn_subheading:      Mapped[Optional[str]]  = mapped_column(String(6))
    description:         Mapped[str]            = mapped_column(Text)
    cbic_description:    Mapped[Optional[str]]  = mapped_column(Text)
    parent_heading_desc: Mapped[Optional[str]]  = mapped_column(Text)
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


# ── Auth helpers ─────────────────────────────────────────────────────────────
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def make_token(sub: str, minutes: int) -> str:
    exp = datetime.utcnow() + timedelta(minutes=minutes)
    return jwt.encode({"sub": sub, "exp": exp}, JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise JWTError("Missing subject")
        return sub
    except (JWTError, KeyError):
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
    alternatives: list[dict] = Field(default_factory=list)
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
        "version": "2.3.0",
    }


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


@app.get("/hsn/{code}", response_model=HSNRow)
async def get_by_code(code: str, db: AsyncSession = Depends(get_db)):
    cached = await cache_get(f"hsn:{code}")
    if cached:
        return cached
    result = await db.execute(
        text("SELECT hsn_code, description, gst_rate, category FROM hsn_codes WHERE hsn_code = :code AND is_active = TRUE LIMIT 1"),
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
    q: Optional[str] = Query(None),
    rate: Optional[float] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(20, le=200),
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


# ── HSN Code Normalization ────────────────────────────────────────────────────
def normalize_hsn_code(hsn_code: Optional[str]) -> Optional[str]:
    """Normalize HSN code to 8 digits with leading zeros. e.g. '8013220' → '08013220'"""
    if not hsn_code:
        return None
    try:
        return str(int(float(hsn_code))).zfill(8)
    except (ValueError, TypeError):
        return hsn_code


@app.post("/expand-abbreviations")
async def expand_abbreviations_endpoint(body: SingleQuery):
    expanded = expand_fmcg_abbreviations(body.text)
    return {"original": body.text, "expanded": expanded, "changed": expanded != body.text}


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
    return {
        "request_id": str(uuid.uuid4()),
        "input_text": body.text,
        "top_match": {
            "hsn_code": normalize_hsn_code(result.hsn_code) or "00009999",
            "description": result.description or "Not classified",
            "score": result.confidence,
            "method": result.match_method,
        },
        "alternatives": [
            {
                "hsn_code": normalize_hsn_code(a.get("hsn_code", "")),
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
            results.append(row)
        except Exception as e:
            await db.rollback()
            results.append(HSNBatchResult(query=query, error=str(e)))

    matched = sum(1 for r in results if r.hsn_code)
    return BatchResponse(results=results, total=len(results), matched=matched, unmatched=len(results) - matched)


# =============================================================================
# MATCHING LOGIC v2.3.0 — Product-Type-First (PTF)
#
# ROOT CAUSE FIX: Old system let ingredient/flavour words override the actual
# product type. The new approach finds product type first, restricts chapter
# search, and falls back to standard FTS / trigram / ILIKE.
# =============================================================================

_PROMO_RE = re.compile(
    r'\b(?:buy\s*\d+\s*get\s*\d+|bogo|free|offer|combo|mrp\s*[\d.]+|rs\.?\s*\d+|\d+\s*%\s*off)\b',
    re.IGNORECASE,
)


def strip_promotional_noise(text: str) -> str:
    cleaned = _PROMO_RE.sub(' ', text)
    return re.sub(r'\s+', ' ', cleaned).strip()


STOPWORDS = {
    'the','a','an','and','or','of','in','is','for','to','with','on','at','by',
    'from','are','was','be','as','it','its','this','that',
    'per','ml','gm','kg','ltr','litre','liter','gram','mg','unit','pcs','set',
    'box','bottle','pouch','sachet','can','tin','jar','tube','strip','pkt',
    'packet','roll','sheet','size','nos',
    'mixed','colour','assorted','round','square','rectangular','oval','flat',
    'long','short','small','large','medium','big','tiny','huge','thick','thin',
    'wide','narrow','high','low','deep','full','empty','half','quarter','whole',
    'various','different','multiple','several','many','few','single','double',
    'triple','regular','extra','standard','basic','advanced','simple','complex',
    'normal','usual','common','rare','unique','ordinary','general','specific',
    'no1','no2','grade','quality','type','variety','model','make','cover',
    'wrapper','wt','weight','net','gross',
    'new','pure','original','brand','best','premium','super','deluxe','fresh',
    'classic','lite','light','rich','real','true','genuine','authentic','select',
    'choice','fine','top','first','plus','pro',
    'loose','bulk','retail','wholesale','branded','unbranded',
}

FLAVOUR_WORDS = {
    'lemon','lime','orange','mango','strawberry','vanilla','chocolate','caramel',
    'butterscotch','pineapple','coconut','almond','pistachio','saffron','rose',
    'mint','berry','cherry','grape','apple','banana','peach','guava','litchi',
    'watermelon','kiwi','passion','cheese','cream','butter',
}

BRANDS = {
    'patanjali','nestle','amul','tata','godrej','dettol','lifebuoy','colgate',
    'pepsodent','nivea','garnier','loreal','sony','samsung','apple','lg',
    'whirlpool','philips','nike','adidas','puma','reebok','bajaj','marico',
    'unilever','parle','sunrise','mogambo','mtr','majestic','micromax','boat',
    'mivi','britannia','honda','suzuki',
    'vkc','cb','cbindal','kitchen','treasure',
    'rasna','yakult','unibic','liya','karthika','star','haldirams','bingo',
    'lays','kurkure','maggi','knorr','sunfeast','priya','eastern','everest',
    'mdh','catch','tat',
}

FMCG_ABBREVIATIONS = {
    'tr':'kitchen treasure','ftgr':'fenugreek','ss':'stainless steel',
    'ss.':'stainless steel','btrm':'bathroom','clnr':'cleaner',
    'dtgnt':'detergent','cookis':'cookie','cashw':'cashew','jasmne':'jasmine',
    'choc':'chocolate','van':'vanilla','strbry':'strawberry','rasbry':'raspberry',
    'bluebry':'blueberry','blkbry':'blackberry','pstr':'pasta','nood':'noodle',
    'sauc':'sauce','ketch':'ketchup','must':'mustard','mayo':'mayonnaise',
    'yog':'yogurt','butr':'butter','marg':'margarine','shamp':'shampoo',
    'cond':'conditioner','det':'detergent','fab':'fabric','soft':'softener',
    'dish':'dishwasher','liq':'liquid','powd':'powder','tab':'tablet',
    'cap':'capsule','syrup':'syrup','vin':'vinegar','sug':'sugar',
    'pick':'pickle','sach':'sachet','cann':'canned','bott':'bottled',
    'cart':'carton','prem':'premium','org':'organic','nat':'natural',
    'imp':'imported','loc':'local','dom':'domestic','froz':'frozen',
    'jeerakam':'cumin','jeerak':'cumin','jeera':'cumin','zeera':'cumin',
    'mulaku':'chilli pepper','manga':'mango','karela':'bitter gourd',
    'pavakka':'bitter gourd','cheera':'spinach','vendakka':'okra',
    'vazhakka':'banana','chena':'yam','chembu':'taro','payar':'beans',
    'ulli':'onion','savola':'shallot','inji':'ginger','malli':'coriander',
    'pottukadalai':'roasted gram','kadalai':'groundnut','ellu':'sesame',
    'kaduku':'mustard seeds','uluva':'fenugreek','perumjeerakam':'fennel',
    'pappada':'pappadam','pappad':'pappadam','papad':'pappadam',
    'pickl':'pickle','achar':'pickle','achaar':'pickle',
    'murukku':'rice snack','chakka':'jackfruit','thenga':'coconut',
    'sambrani':'benzoin incense','pooja':'puja',
    'halwa':'sweet preparation','ladoo':'sweet ball confection',
    'burfi':'sweet confection','mithai':'sweet confection',
    'machne':'machine','mat':'mat','spatule':'spatula','bend':'bend',
    'brut':'brut','db':'db','gents':'mens','ladies':'womens',
    'stainer':'strainer',
}


def expand_fmcg_abbreviations(text: str) -> str:
    text = re.sub(r'\bSS\b', 'stainless steel', text, flags=re.IGNORECASE)
    text = re.sub(r'\bFTGR\b', 'fenugreek', text, flags=re.IGNORECASE)
    text = re.sub(r'\bTR\.\s*', 'kitchen treasure ', text, flags=re.IGNORECASE)
    text = re.sub(r'\bTR\b', 'kitchen treasure', text, flags=re.IGNORECASE)
    text = re.sub(r'\bSTAINER\b', 'strainer', text, flags=re.IGNORECASE)
    words = text.split()
    expanded = [FMCG_ABBREVIATIONS.get(w.lower().rstrip('.'), w) for w in words]
    return ' '.join(expanded).lower()


def tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r'\b\d+\s*(?:ml|g|gm|kg|l|ltr|mg|oz|lb|pc|pcs|nos|x)\b', ' ', text)
    text = re.sub(r'\b\d+\b', ' ', text)
    tokens = re.findall(r'[a-z]{2,}', text)
    return [t for t in tokens if t not in STOPWORDS and t not in BRANDS and len(t) >= 2]


PRODUCT_TYPE_RULES: list[dict] = [
    # HIGH PRIORITY - SPECIFIC PRODUCT TYPES FIRST
    {'keywords':['salt','himalayan','pink salt','rock salt','sea salt','iodised salt','iodized salt'], 'chapters':['25'], 'search_terms':['salt edible table cooking himalayan pink'], 'confidence_boost':0.35},
    {'keywords':['mat','mosquito mat','repellent mat','good knight'], 'chapters':['38'], 'search_terms':['mosquito repellent mat insecticide chemical'], 'confidence_boost':0.32},
    {'keywords':['strainer','sieve','colander','juice strainer','soup strainer'], 'chapters':['39','73'], 'search_terms':['strainer sieve colander kitchen utensil plastic metal'], 'confidence_boost':0.30},
    {'keywords':['utensil','utensils','kitchen utensil','cookware','lid','nob lid'], 'chapters':['73'], 'search_terms':['utensil kitchen cookware lid stainless steel iron'], 'confidence_boost':0.28},
    {'keywords':['spatula','icing spatula','baking tool','kitchen tool'], 'chapters':['82'], 'search_terms':['spatula kitchen tool baking utensil'], 'confidence_boost':0.30},
    {'keywords':['car spray','car freshener','brut','automotive spray'], 'chapters':['33','34'], 'search_terms':['car freshener spray deodorant automotive'], 'confidence_boost':0.28},
    {'keywords':['spray','aerosol','perfume spray','body spray','deodorant spray'], 'chapters':['33'], 'search_terms':['spray aerosol perfume deodorant'], 'confidence_boost':0.25},
    {'keywords':['milk','dairy','curd','yogurt','yoghurt','dahi','lassi','buttermilk','paneer','ghee','fermented milk'], 'chapters':['04'], 'search_terms':['milk dairy curd yogurt butter fermented'], 'confidence_boost':0.22},
    {'keywords':['prawn','shrimp','fish','crab','lobster','squid','pomfret','salmon','tuna','sardine','mackerel','netholi','konju'], 'chapters':['03','16'], 'search_terms':['fish prawn crustacean seafood frozen fresh'], 'confidence_boost':0.22},
    {'keywords':['cumin','jeerakam','jeera','zeera'], 'chapters':['09'], 'search_terms':['cumin seeds anise fennel seeds'], 'confidence_boost':0.38},
    {'keywords':['fenugreek','methi','uluva'], 'chapters':['09'], 'search_terms':['fenugreek seeds spice'], 'confidence_boost':0.35},
    {'keywords':['coriander','malli','dhania'], 'chapters':['09'], 'search_terms':['coriander seeds'], 'confidence_boost':0.30},
    {'keywords':['turmeric','haldi','manjal'], 'chapters':['09'], 'search_terms':['turmeric curcuma ginger saffron'], 'confidence_boost':0.30},
    {'keywords':['cardamom','elaichi','elakkai'], 'chapters':['09'], 'search_terms':['cardamoms nutmeg mace'], 'confidence_boost':0.30},
    {'keywords':['clove','cloves','grambu','lavang'], 'chapters':['09'], 'search_terms':['cloves whole fruit'], 'confidence_boost':0.30},
    {'keywords':['cinnamon','karuvapatta'], 'chapters':['09'], 'search_terms':['cinnamon cinnamon tree flowers'], 'confidence_boost':0.30},
    {'keywords':['ginger','inji'], 'chapters':['09'], 'search_terms':['ginger saffron turmeric curcuma'], 'confidence_boost':0.26},
    {'keywords':['pepper','peppercorn','kurumulaku'], 'chapters':['09'], 'search_terms':['pepper genus piper dried crushed'], 'confidence_boost':0.28},
    {'keywords':['nutmeg','mace','jathikka'], 'chapters':['09'], 'search_terms':['nutmeg mace cardamoms'], 'confidence_boost':0.30},
    {'keywords':['masala','spice mix','curry powder','garam masala','sambar powder','rasam powder'], 'chapters':['09','21'], 'search_terms':['mixed condiments spice preparations masala'], 'confidence_boost':0.22},
    {'keywords':['pickle','pickles','achar','achaar'], 'chapters':['20','21'], 'search_terms':['pickle prepared preserved vegetable vinegar acid'], 'confidence_boost':0.35},
    {'keywords':['pappadam','papad','pappad'], 'chapters':['19'], 'search_terms':['pappadam papad bread food preparation'], 'confidence_boost':0.32},
    {'keywords':['popcorn'], 'chapters':['19'], 'search_terms':['popcorn prepared food swelling cereal roasted puffed'], 'confidence_boost':0.28},
    {'keywords':['cookie','cookies','biscuit','biscuits'], 'chapters':['19'], 'search_terms':['biscuit cookie sweet biscuits pastry'], 'confidence_boost':0.28},
    {'keywords':['wafer','wafers','cracker','crackers'], 'chapters':['19'], 'search_terms':['wafer cracker biscuits bread'], 'confidence_boost':0.22},
    {'keywords':['bread','rusk','toast','crispbread'], 'chapters':['19'], 'search_terms':['bread rusk toast crispbread'], 'confidence_boost':0.22},
    {'keywords':['cake','pastry','muffin','doughnut','cupcake'], 'chapters':['19'], 'search_terms':['cake pastry muffin doughnut'], 'confidence_boost':0.20},
    {'keywords':['chips','crisps','namkeen','bhujia','chakli','mixture','farsan','murukku','sev','chivda'], 'chapters':['19','20'], 'search_terms':['snack cereal preparation prepared food'], 'confidence_boost':0.20},
    {'keywords':['idli','dosa','appam','puttu','upma'], 'chapters':['11','19'], 'search_terms':['semolina cereal flour food preparation'], 'confidence_boost':0.18},
    {'keywords':['protein powder','whey protein','protein shake','health drink','supplement','multivitamin'], 'chapters':['21','30'], 'search_terms':['food preparation protein nutritional supplement'], 'confidence_boost':0.20},
    {'keywords':['coconut oil','thenga oil','palm oil','sunflower oil','groundnut oil','mustard oil','sesame oil','refined oil','cooking oil','edible oil','vegetable oil'], 'chapters':['15'], 'search_terms':['coconut oil palm sunflower edible vegetable oil fats'], 'confidence_boost':0.28},
    {'keywords':['soap','bathing bar','toilet soap','handwash','body wash','face wash','shower gel'], 'chapters':['34'], 'search_terms':['soap toilet organic surface active'], 'confidence_boost':0.26},
    {'keywords':['shampoo'], 'chapters':['33'], 'search_terms':['shampoo preparations hair'], 'confidence_boost':0.28},
    {'keywords':['toothpaste','toothpowder','mouthwash','dental'], 'chapters':['33'], 'search_terms':['oral dental hygiene toothpaste preparations'], 'confidence_boost':0.30},
    {'keywords':['cream','lotion','moisturizer','moisturiser','sunscreen','face cream','body lotion'], 'chapters':['33'], 'search_terms':['beauty skincare preparations cream lotion'], 'confidence_boost':0.22},
    {'keywords':['perfume','cologne','deodorant','deo','antiperspirant'], 'chapters':['33'], 'search_terms':['perfume toilet water deodorant'], 'confidence_boost':0.26},
    {'keywords':['agarbatti','incense','dhoop','sambrani'], 'chapters':['33'], 'search_terms':['agarbatti odoriferous preparations incense'], 'confidence_boost':0.32},
    {'keywords':['detergent','washing powder','laundry','fabric wash','dishwash','utensil wash','rinse'], 'chapters':['34'], 'search_terms':['detergent washing cleaning surface active'], 'confidence_boost':0.26},
    {'keywords':['slipper','slippers','chappal','chappals','sandal','sandals','shoe','shoes','boot','boots','hawai','footwear'], 'chapters':['64'], 'search_terms':['footwear slipper sandal shoe rubber plastics outer sole'], 'confidence_boost':0.26},
    {'keywords':['phone','mobile','smartphone','handset'], 'chapters':['85'], 'search_terms':['mobile phone smartphone telephone sets video'], 'confidence_boost':0.26},
    {'keywords':['laptop','computer'], 'chapters':['84'], 'search_terms':['automatic data processing computer laptop notebook'], 'confidence_boost':0.26},
    {'keywords':['television','led tv','lcd tv','smart tv'], 'chapters':['85'], 'search_terms':['television monitor receiver'], 'confidence_boost':0.26},
    {'keywords':['notebook','exercise book','writing pad','notepad'], 'chapters':['48'], 'search_terms':['registers account books notebooks paper'], 'confidence_boost':0.26},
    {'keywords':['pen','pencil','crayon','marker','highlighter'], 'chapters':['96'], 'search_terms':['pen pencil crayon writing instruments'], 'confidence_boost':0.22},
    {'keywords':['stainless steel','stainless'], 'chapters':['73'], 'search_terms':['stainless steel table kitchen household iron articles'], 'confidence_boost':0.28},
    {'keywords':['shirt','tshirt','trouser','pant','saree','kurta','kurthi','dress','blouse','skirt','jacket','leggings','churidar','salwar','dupatta','veshti','dhoti','lunghi','mundu'], 'chapters':['61','62'], 'search_terms':['garment clothing knitted woven apparel'], 'confidence_boost':0.22},
    {'keywords':['rice','basmati','matta'], 'chapters':['10'], 'search_terms':['rice'], 'confidence_boost':0.26},
    {'keywords':['wheat','atta','maida','flour'], 'chapters':['10','11'], 'search_terms':['wheat flour atta meslin'], 'confidence_boost':0.22},
    {'keywords':['dal','dhal','lentil','moong','urad','toor','chana','masoor','rajma','kadala'], 'chapters':['07'], 'search_terms':['dried leguminous vegetables dal lentil peas'], 'confidence_boost':0.26},
    {'keywords':['chutney','relish'], 'chapters':['20','21'], 'search_terms':['chutney sauce preparation'], 'confidence_boost':0.28},
    {'keywords':['jam','jelly','marmalade'], 'chapters':['20'], 'search_terms':['jam jelly marmalade fruit'], 'confidence_boost':0.26},
    {'keywords':['sauce','ketchup'], 'chapters':['21'], 'search_terms':['sauce preparations condiment ketchup tomato'], 'confidence_boost':0.22},
    {'keywords':['candy','toffee','lollipop'], 'chapters':['17'], 'search_terms':['sugar confectionery candy toffee'], 'confidence_boost':0.24},
    {'keywords':['chocolate'], 'chapters':['18'], 'search_terms':['chocolate cocoa food preparations'], 'confidence_boost':0.24},
    {'keywords':['ladoo','laddoo','burfi','halwa','mithai','peda','barfi','modak','jalebi'], 'chapters':['17','21'], 'search_terms':['sugar confectionery sweet preparation'], 'confidence_boost':0.20},
    {'keywords':['tea','chai'], 'chapters':['09'], 'search_terms':['tea green black'], 'confidence_boost':0.26},
    {'keywords':['coffee'], 'chapters':['09','21'], 'search_terms':['coffee roasted unroasted'], 'confidence_boost':0.24},
    {'keywords':['squash','cordial'], 'chapters':['22'], 'search_terms':['squash fruit drink concentrate waters flavoured sugar'], 'confidence_boost':0.32},
    {'keywords':['juice'], 'chapters':['20','22'], 'search_terms':['fruit juice vegetable juice'], 'confidence_boost':0.22},
    {'keywords':['drink','drinks','beverage','beverages'], 'chapters':['22'], 'search_terms':['beverage drink waters'], 'confidence_boost':0.18},
    {'keywords':['soda','cola','lemonade','sherbet','sharbat'], 'chapters':['22'], 'search_terms':['waters sugar flavour aerated soda'], 'confidence_boost':0.22},
    {'keywords':['water'], 'chapters':['22'], 'search_terms':['mineral water drinking waters'], 'confidence_boost':0.18},
]


_ALL_PRODUCT_KEYWORDS: dict[str, dict] = {}
for _rule in PRODUCT_TYPE_RULES:
    for _kw in _rule['keywords']:
        if ' ' not in _kw:
            _ALL_PRODUCT_KEYWORDS[_kw] = _rule


def extract_product_type(tokens: list[str], raw_text: str) -> Optional[dict]:
    raw_lower = raw_text.lower()
    for rule in PRODUCT_TYPE_RULES:
        for kw in rule['keywords']:
            if ' ' not in kw:
                if kw in tokens:
                    return rule
            else:
                if kw in raw_lower:
                    return rule
    return None


SYNONYMS = {
    'wash':['soap','cleanser'],'phone':['mobile','smartphone'],'tv':['television'],
    'fridge':['refrigerator'],'laptop':['notebook'],
    'chappal':['sandal','footwear','slipper'],'slipper':['sandal','footwear','chappal'],
    'sandal':['footwear','slipper','chappal'],'shoe':['footwear'],'hawai':['slipper','footwear'],
    'stainless':['steel','metal'],'fenugreek':['methi','spice'],'methi':['fenugreek','spice'],
    'cumin':['jeera','seed','spice'],'jeera':['cumin','seed','spice'],
    'pickle':['achar','preserved','vinegar'],'achar':['pickle','preserved'],
    'popcorn':['corn','cereal','snack'],'squash':['drink','beverage','concentrate'],
    'cookie':['biscuit','confectionery'],'biscuit':['cookie','confectionery'],
    'pappadam':['papad','flatbread'],'papad':['pappadam','flatbread'],
    'salt':['himalayan','pink','rock','sea','iodised','iodized'],
    'mat':['mosquito','repellent','good knight'],'strainer':['sieve','colander'],
    'utensil':['cookware','kitchen tool'],'spatula':['baking tool','kitchen tool'],
    'spray':['aerosol','freshener'],'car':['automotive'],
}

DOMAIN_PREFIXES: dict[str, list[str]] = {
    'footwear':['64'],'sandal':['64'],'slipper':['64'],'chappal':['64'],
    'shoe':['64'],'boot':['64'],'stainless':['73'],'steel':['73'],
    'fenugreek':['09'],'methi':['09'],'cumin':['09'],'jeera':['09'],
    'spice':['09'],'masala':['09','21'],'biscuit':['19'],'cookie':['19'],
    'bread':['19'],'popcorn':['19'],'snack':['19'],'pappadam':['19'],
    'drink':['22'],'beverage':['22'],'water':['22'],'juice':['20','22'],
    'squash':['22'],'soap':['34'],'handwash':['34'],'shampoo':['33'],
    'cream':['33'],'pickle':['20'],'achar':['20'],'jam':['20'],
    'phone':['85'],'mobile':['85'],'tv':['85'],'computer':['84'],
    'laptop':['84'],'notebook':['48'],'salt':['25'],'himalayan':['25'],
    'mat':['38'],'mosquito':['38'],'repellent':['38'],'strainer':['39','73'],
    'sieve':['39','73'],'colander':['39','73'],'utensil':['73'],'cookware':['73'],
    'spatula':['82'],'baking':['82'],'spray':['33','34'],'car':['33','34'],
}

CATEGORY_RULES = [
    {'keywords':['tooth','paste','toothpaste'],'chapters':['33']},
    {'keywords':['computer','laptop'],'chapters':['84']},
    {'keywords':['notebook','exercise book'],'chapters':['48']},
    {'keywords':['puja','agarbatti'],'chapters':['33']},
    {'keywords':['footwear','sandal','slipper','chappal','shoe'],'chapters':['64']},
    {'keywords':['stainless','steel'],'chapters':['73']},
    {'keywords':['popcorn'],'chapters':['19']},
    {'keywords':['cookie','biscuit','wafer'],'chapters':['19']},
    {'keywords':['pappadam','papad'],'chapters':['19']},
    {'keywords':['squash','cordial'],'chapters':['22']},
    {'keywords':['pickle','achar'],'chapters':['20']},
    {'keywords':['cumin','jeera','jeerakam'],'chapters':['09']},
    {'keywords':['fenugreek','methi'],'chapters':['09']},
    {'keywords':['soap','handwash'],'chapters':['34']},
    {'keywords':['shampoo'],'chapters':['33']},
    {'keywords':['phone','mobile'],'chapters':['85']},
    {'keywords':['masala','spice'],'chapters':['09','21']},
    {'keywords':['drink','beverage','juice','water'],'chapters':['22']},
    {'keywords':['pickle','jam','preserve'],'chapters':['20']},
    {'keywords':['salt','himalayan','pink salt'],'chapters':['25']},
    {'keywords':['mat','mosquito','repellent'],'chapters':['38']},
    {'keywords':['strainer','sieve','colander'],'chapters':['39','73']},
    {'keywords':['utensil','cookware','lid'],'chapters':['73']},
    {'keywords':['spatula','baking','kitchen tool'],'chapters':['82']},
    {'keywords':['spray','car','freshener'],'chapters':['33','34']},
]

PLACEHOLDER_BOOST_CHAPTERS = {'33','34','39','96'}


def _apply_placeholder_boost(hsn_code: str, score: float) -> float:
    chapter = hsn_code[:2] if len(hsn_code) >= 2 else ''
    return min(score * 1.05, 1.0) if chapter in PLACEHOLDER_BOOST_CHAPTERS else score


def detect_category_chapters(tokens: list[str]) -> list[str]:
    for rule in CATEGORY_RULES:
        if any(kw in tokens for kw in rule['keywords']):
            return rule['chapters']
    return []


def build_prefix_clause(chapters: list[str], alias: str = "h") -> tuple[str, dict]:
    if not chapters:
        return "", {}
    parts, params = [], {}
    for i, ch in enumerate(sorted(set(chapters))):
        k = f"prefix_{i}"
        parts.append(f"{alias}.hsn_code LIKE :{k}")
        params[k] = f"{ch}%"
    return " AND (" + " OR ".join(parts) + ")", params


def build_prefix_clause_from_tokens(tokens: list[str], alias: str = "h") -> tuple[str, dict]:
    chapters = detect_category_chapters(tokens)
    if not chapters:
        expanded = set(tokens)
        for t in tokens:
            expanded.update(SYNONYMS.get(t, []))
        chapters = []
        for t in expanded:
            chapters.extend(DOMAIN_PREFIXES.get(t, []))
    return build_prefix_clause(chapters, alias)


def build_tsquery_terms(tokens: list[str]) -> list[str]:
    result = []
    for t in tokens:
        variants = [t] + SYNONYMS.get(t, [])
        result.append("(" + " | ".join(variants) + ")" if len(variants) > 1 else t)
    return result


def compute_weighted_jaccard(tokens: list[str], desc_tokens: set[str]) -> float:
    weights: dict[str, int] = {}
    for t in tokens:
        weights[t] = max(weights.get(t, 0), 2)
        for s in SYNONYMS.get(t, []):
            weights[s] = max(weights.get(s, 0), 1)
    inter = sum(w for t, w in weights.items() if t in desc_tokens)
    union = sum(weights.values()) + len(desc_tokens) - inter
    return min(inter / union, 1.0) if union > 0 else 0.0


async def _match_one(query: str, db: AsyncSession) -> HSNBatchResult:
    q_stripped = query.strip()

    # Step 0: Exact lookup in verified products
    desc_normalized = q_stripped.upper().strip()
    try:
        res = await db.execute(
            text("SELECT hsn_code, description, gst_rate FROM verified_products WHERE description_normalized = :d"),
            {"d": desc_normalized}
        )
        row = res.fetchone()
        if row:
            gst_val = float(row.gst_rate) if row.gst_rate else 0.0
            return HSNBatchResult(query=query, hsn_code=row.hsn_code, description=row.description, 
                                  gst_rate=gst_val, confidence=1.0, 
                                  confidence_label="high", match_method="exact_verified")
    except Exception:
        pass

    if re.match(r'^\d{4,8}$', q_stripped):
        res = await db.execute(
            text("SELECT h.hsn_code, h.description, h.gst_rate, h.category FROM hsn_codes h WHERE h.hsn_code = :code AND h.is_active = TRUE LIMIT 1"),
            {"code": q_stripped},
        )
        row = res.fetchone()
        if row:
            return HSNBatchResult(query=query, hsn_code=row.hsn_code, description=row.description, gst_rate=float(row.gst_rate or 0), confidence=1.0, confidence_label="high", match_method="exact_code")

    q_clean = strip_promotional_noise(q_stripped)
    q_exp = expand_fmcg_abbreviations(q_clean)
    tokens = tokenize(q_exp)
    if not tokens:
        return HSNBatchResult(query=query, match_method="none")

    pt_rule = extract_product_type(tokens, q_exp)
    if pt_rule:
        st_words = [w for term in pt_rule['search_terms'] for w in term.split()]
        non_flavour = [t for t in tokens if t not in FLAVOUR_WORDS]
        combined = list(dict.fromkeys(st_words + non_flavour))
        chapters = pt_rule['chapters']
        boost = pt_rule['confidence_boost']
        dom_clause, dom_params = build_prefix_clause(chapters)
        fts_words = [t for t in combined if len(t) >= 3][:10]

        for ts_q in [" & ".join(fts_words[:8]), " | ".join(fts_words[:8])]:
            if not ts_q:
                continue
            try:
                res = await db.execute(
                    text("""
                        SELECT h.hsn_code, h.description, h.gst_rate, h.category,
                               ts_rank(s.search_vector, query) AS rank
                        FROM hsn_search s
                        JOIN hsn_codes h ON h.hsn_code = s.hsn_code
                        CROSS JOIN to_tsquery('english', :q) query
                        WHERE s.search_vector @@ query AND h.is_active = TRUE
                    """ + dom_clause + " ORDER BY rank DESC LIMIT 10"),
                    {"q": ts_q, **dom_params},
                )
                rows = res.fetchall()
                if rows:
                    best = rows[0]
                    raw = min(float(best.rank) * 2.5 + 0.3, 0.85)
                    final = min(raw + boost, 0.95)
                    label = "high" if final >= 0.65 else ("medium" if final >= 0.35 else "low")
                    alts = [{"hsn_code": r.hsn_code, "description": r.description, "gst_rate": float(r.gst_rate or 0), "confidence": round(min(float(r.rank)*2.5+boost, 0.90), 3)} for r in rows[1:4]]
                    return HSNBatchResult(query=query, hsn_code=best.hsn_code, description=best.description, gst_rate=float(best.gst_rate or 0), confidence=round(final, 3), confidence_label=label, match_method="product_type_fts", alternatives=alts)
            except Exception:
                pass

        il_clause, il_params = build_prefix_clause(chapters, "hsn_codes")
        cands: dict[str, dict] = {}
        for term in pt_rule['search_terms'][:3]:
            for word in term.split()[:2]:
                if len(word) >= 4:
                    try:
                        res = await db.execute(
                            text("SELECT hsn_code, description, gst_rate, category FROM hsn_codes WHERE description ILIKE :pat AND is_active = TRUE" + il_clause + " LIMIT 15"),
                            {"pat": f"%{word}%", **il_params},
                        )
                        for r in res.fetchall():
                            if r.hsn_code not in cands:
                                cands[r.hsn_code] = {"hsn_code": r.hsn_code, "description": r.description, "gst_rate": float(r.gst_rate or 0), "hits": 0}
                            cands[r.hsn_code]["hits"] += 1
                    except Exception:
                        await db.rollback()

        if cands:
            n = max(len(pt_rule['search_terms']), 1)
            scored = sorted([(min(c["hits"]/n + boost, 0.90), c) for c in cands.values()], key=lambda x: x[0], reverse=True)
            top_s, top_c = scored[0]
            label = "high" if top_s >= 0.65 else ("medium" if top_s >= 0.35 else "low")
            alts = [{"hsn_code": c["hsn_code"], "description": c["description"], "gst_rate": c["gst_rate"], "confidence": round(s, 3)} for s, c in scored[1:4] if s > 0]
            return HSNBatchResult(query=query, hsn_code=top_c["hsn_code"], description=top_c["description"], gst_rate=top_c["gst_rate"], confidence=round(top_s, 3), confidence_label=label, match_method="product_type_ilike", alternatives=alts)

    dom_clause, dom_params = build_prefix_clause_from_tokens(tokens)
    ts_terms = build_tsquery_terms(tokens)
    rows_fts = []
    for ts_q in [" & ".join(ts_terms[:8]), " | ".join(ts_terms[:8])]:
        try:
            res = await db.execute(
                text("""
                    SELECT h.hsn_code, h.description, h.gst_rate, h.category,
                           ts_rank(s.search_vector, query) AS rank
                    FROM hsn_search s
                    JOIN hsn_codes h ON h.hsn_code = s.hsn_code
                    CROSS JOIN to_tsquery('english', :q) query
                    WHERE s.search_vector @@ query AND h.is_active = TRUE
                """ + dom_clause + " ORDER BY rank DESC LIMIT 15"),
                {"q": ts_q, **dom_params},
            )
            rows_fts = res.fetchall()
            if rows_fts:
                break
        except Exception:
            rows_fts = []

    if rows_fts:
        best = None
        best_s = 0.0
        alts = []
        for r in rows_fts:
            dt = set(tokenize(r.description))
            if not dt:
                continue
            j = compute_weighted_jaccard(tokens, dt)
            fs = min(float(r.rank) * 2.5, 0.4)
            final = _apply_placeholder_boost(r.hsn_code, min(j*0.6+fs, 1.0))
            entry = {"hsn_code": r.hsn_code, "description": r.description, "gst_rate": float(r.gst_rate or 0), "confidence": round(final, 3)}
            if final > best_s:
                if best:
                    alts.append(best)
                best = entry
                best_s = final
            else:
                alts.append(entry)
        if best and best_s > 0.05:
            label = "high" if best_s >= 0.65 else ("medium" if best_s >= 0.35 else "low")
            return HSNBatchResult(query=query, hsn_code=best["hsn_code"], description=best["description"], gst_rate=best["gst_rate"], confidence=round(best_s, 3), confidence_label=label, match_method="fulltext_fts", alternatives=alts[:4])

    try:
        tq = " ".join(tokens[:6])
        res = await db.execute(
            text("""
                SELECT h.hsn_code, h.description, h.gst_rate, h.category,
                       similarity(s.normalized_description, :q) AS sim
                FROM hsn_search s
                JOIN hsn_codes h ON h.hsn_code = s.hsn_code
                WHERE s.normalized_description % :q AND h.is_active = TRUE
            """ + dom_clause + " ORDER BY sim DESC LIMIT 10"),
            {"q": tq, **dom_params},
        )
        rows_tg = res.fetchall()
    except Exception:
        rows_tg = []

    if rows_tg:
        best = rows_tg[0]
        ss = _apply_placeholder_boost(best.hsn_code, float(best.sim))
        if ss > 0.15:
            label = "high" if ss >= 0.60 else ("medium" if ss >= 0.30 else "low")
            alts = [{"hsn_code": r.hsn_code, "description": r.description, "gst_rate": float(r.gst_rate or 0), "confidence": round(_apply_placeholder_boost(r.hsn_code, float(r.sim)), 3)} for r in rows_tg[1:4]]
            return HSNBatchResult(query=query, hsn_code=best.hsn_code, description=best.description, gst_rate=float(best.gst_rate or 0), confidence=round(ss, 3), confidence_label=label, match_method="trigram", alternatives=alts)

    il_clause, il_params = build_prefix_clause_from_tokens(tokens, "hsn_codes")
    cands: dict[str, dict] = {}
    for t in tokens[:4]:
        if len(t) < 3:
            continue
        try:
            res = await db.execute(
                text("SELECT hsn_code, description, gst_rate, category FROM hsn_codes WHERE description ILIKE :pat AND is_active = TRUE" + il_clause + " LIMIT 20"),
                {"pat": f"%{t}%", **il_params},
            )
            for r in res.fetchall():
                if r.hsn_code not in cands:
                    cands[r.hsn_code] = {"hsn_code": r.hsn_code, "description": r.description, "gst_rate": float(r.gst_rate or 0), "hits": 0}
                cands[r.hsn_code]["hits"] += 1
        except Exception:
            await db.rollback()
            break

    if cands:
        n = max(len(tokens), 1)
        scored = sorted([(_apply_placeholder_boost(c["hsn_code"], c["hits"]/n), c) for c in cands.values()], key=lambda x: x[0], reverse=True)
        top_s, top_c = scored[0]
        if top_s > 0.1:
            label = "high" if top_s >= 0.65 else ("medium" if top_s >= 0.35 else "low")
            alts = [{"hsn_code": c["hsn_code"], "description": c["description"], "gst_rate": c["gst_rate"], "confidence": round(s, 3)} for s, c in scored[1:4] if s > 0]
            return HSNBatchResult(query=query, hsn_code=top_c["hsn_code"], description=top_c["description"], gst_rate=top_c["gst_rate"], confidence=round(top_s, 3), confidence_label=label, match_method="keyword_ilike", alternatives=alts)

    return HSNBatchResult(query=query, match_method="none")


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
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)"))
