from __future__ import annotations
import csv
import os
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

import structlog
from app.config import settings

log = structlog.get_logger()

_db_url = settings.async_database_url
_is_sqlite = "sqlite" in _db_url

engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
}

if _is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["poolclass"] = NullPool
    engine_kwargs["connect_args"] = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "ssl": "require",
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


_DATA_PATH = Path(os.getenv("HSN_DATA_PATH", "data/hsn_codes.csv"))


async def _seed_hsn_codes(session: AsyncSession) -> None:
    """Seed hsn_codes table from CSV if the table is empty."""
    if not _DATA_PATH.exists():
        log.warning("seed.csv_missing", path=str(_DATA_PATH))
        return

    result = await session.execute(select(func.count()).select_from(HsnCode))
    count = result.scalar()
    if count and count > 0:
        log.info("seed.already_seeded", count=count)
        return

    rows = []
    with open(_DATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            hsn = row.get("hsn_code", "").strip()
            desc = row.get("description", "").strip()
            if hsn and desc:
                rows.append(HsnCode(hsn_code=hsn, description=desc, source="CSV"))

    if not rows:
        log.warning("seed.no_rows_in_csv")
        return

    session.add_all(rows)
    await session.commit()
    log.info("seed.hsn_codes_done", count=len(rows))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        await _seed_hsn_codes(session)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
