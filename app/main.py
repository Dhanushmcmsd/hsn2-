from __future__ import annotations
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
from app.utils.metrics import metrics_endpoint          # existing Prometheus handler
from app.utils.scheduler import start_scheduler, stop_scheduler  # GST cron
from app.utils.seed import seed_default_org             # multi-tenancy seed
from app.routes import predict, review, health, auth, admin, hsn
from app.routes.admin_orgs import router as admin_orgs_router

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
    _validate_production_config()
    await init_db()
    await init_cache()
    await start_scheduler()          # starts AsyncIOScheduler + registers GST cron
    await seed_default_org()         # ensure HQ org + Default Branch exist
    log.info("app.startup", env=settings.APP_ENV)
    yield
    await stop_scheduler()           # clean shutdown
    log.info("app.shutdown")


app = FastAPI(
    title="HSN Classifier",
    version="1.0.0",
    description="AI-powered HSN/GST code classifier for Indian products",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
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


app.include_router(auth.router)
app.include_router(predict.router)
app.include_router(review.router)
app.include_router(health.router)
app.include_router(admin.router)
app.include_router(hsn.router)
app.include_router(admin_orgs_router)   # multi-tenancy admin API

# Prometheus metrics endpoint — exposes all registered gauges/counters/histograms
app.add_route("/metrics", metrics_endpoint)
