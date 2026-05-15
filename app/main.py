from __future__ import annotations
import asyncio
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config as app_config
from app.config import settings, DEV_SECRET, DEV_API_KEY, DEV_ADMIN_KEY
from app.models.database import init_db
from app.utils.logging import configure_logging
from app.utils.cache import init_cache
from app.utils.scheduler import start_scheduler, stop_scheduler
from app.routes import predict, review, health, auth, admin, hsn, search

configure_logging()
log = structlog.get_logger()


def _validate_production_config():
    cfg = app_config.settings
    if not cfg.is_production:
        return
    errors = []
    if cfg.SECRET_KEY == DEV_SECRET or "change-me" in cfg.SECRET_KEY:
        errors.append("SECRET_KEY must not be the default placeholder")
    if cfg.API_KEY == DEV_API_KEY:
        errors.append("API_KEY must not be the default placeholder")
    if cfg.ADMIN_API_KEY == DEV_ADMIN_KEY:
        errors.append("ADMIN_API_KEY must not be the default placeholder")
    if cfg.API_KEY == cfg.ADMIN_API_KEY:
        errors.append("API_KEY and ADMIN_API_KEY must be different")
    if "sqlite" in cfg.DATABASE_URL:
        errors.append("DATABASE_URL must be PostgreSQL in production")
    if "*" in cfg.CORS_ORIGINS:
        errors.append("CORS_ORIGINS wildcard * is not allowed in production")
    if errors:
        raise RuntimeError("Production startup validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ready = False
    _validate_production_config()
    await init_db()
    await init_cache()

    async def warm_matcher_blocking():
        try:
            from app.services.matcher import get_matcher

            def _load():
                matcher = get_matcher()
                return matcher

            matcher = await asyncio.to_thread(_load)
            if matcher.ready:
                log.info("matcher.warmup_complete", faiss_ready=True)
            else:
                log.warning("matcher.warmup_complete", faiss_ready=False, note="semantic_search_disabled_until_faiss_loads")
            return matcher.ready
        except Exception as exc:
            log.error("matcher.warmup_failed", error=str(exc))
            return False

    async def warm_search_layer():
        try:
            from app.models.database import async_session
            from app.services import multi_layer_search

            async with async_session() as session:
                await multi_layer_search.warmup(session)
            log.info("search.warmup_complete")
        except Exception as exc:
            log.warning("search.warmup_failed", error=str(exc))

    faiss_ok = await warm_matcher_blocking()
    app.state.matcher_semantic_ready = faiss_ok
    app.state.ready = True

    try:
        from app.models.database import async_session
        from sqlalchemy import text
        async with async_session() as session:
            rows = await session.execute(text("""
                SELECT description, hsn_code, gst_rate, description 
                FROM verified_products
            """))
            app.state.product_name_cache = [
                (r[0], r[1], str(r[2]) if r[2] is not None else "", r[3]) for r in rows.fetchall()
            ]
        log.info(f"Product name cache loaded: {len(app.state.product_name_cache)} entries")
    except Exception as exc:
        log.warning("product_name_cache.load_failed", error=str(exc))
        app.state.product_name_cache = []

    await start_scheduler()

    asyncio.create_task(warm_search_layer())
    log.info("app.startup", env=settings.APP_ENV, accepts_requests=app.state.ready)
    yield

    await stop_scheduler()
    log.info("app.shutdown")


app = FastAPI(
    title="HSN Classifier",
    version="1.0.0",
    description="AI-powered HSN/GST code classifier for Indian products",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{elapsed:.1f}"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(search.router)
app.include_router(auth.router)
app.include_router(predict.router)
app.include_router(review.router)
app.include_router(health.router)
app.include_router(admin.router)
app.include_router(hsn.router)
