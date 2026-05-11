from __future__ import annotations
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config as app_config
from app.config import settings, DEV_SECRET, DEV_API_KEY, DEV_ADMIN_KEY
from app.models.database import init_db
from app.utils.logging import configure_logging
from app.utils.cache import init_cache
from app.utils.metrics import metrics_endpoint
from app.utils.scheduler import start_scheduler, stop_scheduler
from app.utils.seed import seed_default_org
from app.routes import predict, review, health, auth, admin, hsn, admin_orgs, admin_users
from app.routes import reports, analytics

configure_logging()
log = structlog.get_logger()
request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)


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
    await seed_default_org()
    await init_cache()
    await start_scheduler()
    log.info("app.startup", env=settings.APP_ENV)
    yield
    await stop_scheduler()
    log.info("app.shutdown")


tags_metadata = [
    {"name": "Authentication", "description": "Login, API key and token workflows."},
    {"name": "Classification", "description": "HSN prediction and lookup endpoints."},
    {"name": "Reports", "description": "GST summary and compliance reports."},
    {"name": "Admin", "description": "Administrative and governance operations."},
    {"name": "Health", "description": "System health and observability endpoints."},
]

app = FastAPI(
    title="HSN Classifier API",
    version="2.0.0",
    description="AI-powered HSN code classification and GST rate lookup for Indian businesses.",
    contact={"name": "Support", "email": "support@yourdomain.com"},
    license_info={"name": "Proprietary"},
    terms_of_service="https://yourdomain.com/terms",
    openapi_tags=tags_metadata,
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
    request_id_ctx_var.set(request_id)
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{elapsed:.1f}"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; object-src 'none'"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    log.warning(
        "request_validation_error",
        path=request.url.path,
        errors=exc.errors(),
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request payload", "request_id": getattr(request.state, "request_id", None)},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(auth.router)
app.include_router(predict.router)
app.include_router(review.router)
app.include_router(health.router)
app.include_router(admin.router)
app.include_router(admin_users.router)
app.include_router(admin_orgs.router)
app.include_router(hsn.router)
app.include_router(reports.router)
app.include_router(analytics.router)

app.add_route("/metrics", metrics_endpoint)
