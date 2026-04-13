from __future__ import annotations
from functools import lru_cache
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "change-me-32-chars-minimum"
DEV_API_KEY = "dev-api-key"
DEV_ADMIN_KEY = "dev-admin-key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    SECRET_KEY: str = DEV_SECRET
    API_KEY: str = DEV_API_KEY
    ADMIN_API_KEY: str = DEV_ADMIN_KEY

    DATABASE_URL: str = "sqlite+aiosqlite:///./hsn_dev.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    CORS_ORIGINS: str = "http://localhost:3000"

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    METRICS_PASSWORD: str = ""

    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    TOP_K: int = 5
    CONFIDENCE_HIGH: float = 0.80
    CONFIDENCE_MEDIUM: float = 0.55
    REVIEW_THRESHOLD: float = 0.55
    AMBIGUITY_THRESHOLD: float = 0.10
    CACHE_TTL: int = 3600
    RATE_LIMIT_PER_MINUTE: int = 60

    @property
def DATABASE_URL(self) -> str:
    url = self._database_url  # your raw env var field
    # Render injects postgres:// — fix it for asyncpg
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url
    
    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
