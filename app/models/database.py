from __future__ import annotations
from typing import AsyncGenerator

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings


_db_url = settings.async_database_url
_is_sqlite = "sqlite" in _db_url

engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
}

if _is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Render / pgbouncer in transaction/statement mode does not support asyncpg
    # prepared statement caching. Disable both asyncpg statement cache and the
    # SQLAlchemy asyncpg prepared statement cache.
    engine_kwargs["poolclass"] = NullPool
    engine_kwargs["connect_args"] = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }

engine = create_async_engine(_db_url, **engine_kwargs)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(36), unique=True, index=True, nullable=False)
    input_text = Column(Text, nullable=False)
    predicted_hsn = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=False)
    needs_review = Column(Boolean, default=False)
    resolved = Column(Boolean, default=False)
    corrected_hsn = Column(String(20), nullable=True)
    api_key_hash = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    key_hash = Column(String(64), unique=True, index=True)
    label = Column(String(100), nullable=True)
    tier = Column(String(20), default="standard")
    is_active = Column(Boolean, default=True)
    requests_today = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class HsnCode(Base):
    """HSN / HS Code master reference table."""
    __tablename__ = "hsn_codes"

    id          = Column(Integer, primary_key=True, index=True)
    hsn_code    = Column(String(10),  unique=True, index=True, nullable=False)
    description = Column(Text,        nullable=False)
    source      = Column(String(50),  nullable=False, default="WCO_HS")
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "idx_hsn_codes_description_gin",
            func.to_tsvector("english", description),
            postgresql_using="gin",
        ),
    )


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
