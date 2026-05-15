from __future__ import annotations
import asyncio
import csv
import os
import re
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

import structlog
from app.config import settings
from app.services.hsn_master import build_hsn_master_records

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
_SCHEMA_LOCK = asyncio.Lock()
_SCHEMA_DONE = False
_INIT_LOCK = asyncio.Lock()
_INIT_DONE = False


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
    source = Column(String(50), nullable=True)
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

    id = Column(Integer, primary_key=True, index=True)
    hsn_code = Column(String(10), unique=True, index=True, nullable=False)
    hsn_chapter = Column(String(2), nullable=True)
    hsn_heading = Column(String(4), nullable=True)
    hsn_subheading = Column(String(6), nullable=True)
    description = Column(Text, nullable=False)
    cbic_description = Column(Text, nullable=True)
    parent_heading_desc = Column(Text, nullable=True)
    gst_rate = Column(Float, nullable=True)
    category = Column(String(100), nullable=True)
    schedule = Column(String(150), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    source = Column(String(50), nullable=False, default="WCO_HS")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        ()
        if _is_sqlite
        else (
            Index(
                "idx_hsn_codes_description_gin",
                func.to_tsvector("english", description),
                postgresql_using="gin",
            ),
        )
    )


class VerifiedProduct(Base):
    """
    Pre-verified products from correct_datas.xlsx for exact/fast lookup.

    Two normalised forms are stored for two-pass matching:
      • description_normalized  – exact UPPERCASE of original (unique per row)
      • description_no_size     – size tokens stripped (e.g. "500ML", "1KG" removed)
                                  used for fuzzy fallback when exact fails
    """
    __tablename__ = "verified_products"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(Text, nullable=False)

    # Pass-0A: exact uppercase match
    description_normalized = Column(String(500), unique=True, index=True, nullable=False)

    # Pass-0B: size-stripped match (NOT unique — multiple sizes collapse here)
    description_no_size = Column(String(500), nullable=True, index=True)

    hsn_code = Column(String(10), nullable=False, index=True)
    gst_rate = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_verified_desc", "description_normalized"),
        Index("idx_verified_no_size", "description_no_size"),
    )


# ── Normalisation helpers ──────────────────────────────────────────────────────

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
    """Remove weight/volume/count tokens; collapse whitespace; return UPPERCASE."""
    t = _SIZE_PAT.sub(' ', text.upper())
    t = re.sub(r'[^A-Z\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _clean_hsn(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    digits = re.sub(r'[^0-9]', '', str(raw).strip())
    return digits.zfill(8) if digits else None


def _clean_gst(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    m = re.search(r'(\d+)', str(raw))
    return m.group(1) + '%' if m else None


# ── Data paths ─────────────────────────────────────────────────────────────────

_DATA_PATH = Path(os.getenv("HSN_DATA_PATH", "data/hsn_codes.csv"))
_VERIFIED_DATA_PATH = Path(os.getenv("VERIFIED_DATA_PATH", "data/correct_datas.xlsx"))


async def _seed_hsn_codes(session: AsyncSession) -> None:
    """Seed hsn_codes from the enriched local master view."""
    records = build_hsn_master_records()
    if not records:
        log.warning("seed.hsn_codes_missing")
        return

    existing_rows = {
        row.hsn_code: row
        for row in (await session.execute(select(HsnCode))).scalars().all()
    }
    target_codes = {record["hsn_code"] for record in records}

    removed = 0
    for hsn_code, row in list(existing_rows.items()):
        if hsn_code not in target_codes:
            await session.delete(row)
            removed += 1

    added = 0
    updated = 0
    tracked_fields = (
        "hsn_chapter",
        "hsn_heading",
        "hsn_subheading",
        "description",
        "cbic_description",
        "parent_heading_desc",
        "gst_rate",
        "category",
        "schedule",
        "is_active",
        "source",
    )

    for record in records:
        current = existing_rows.get(record["hsn_code"])
        if current is None:
            session.add(HsnCode(**record))
            added += 1
            continue

        changed = False
        for field in tracked_fields:
            if getattr(current, field) != record[field]:
                setattr(current, field, record[field])
                changed = True
        if changed:
            updated += 1

    await session.commit()
    log.info(
        "seed.hsn_codes_done",
        count=len(records),
        added=added,
        updated=updated,
        removed=removed,
    )


async def _seed_verified_products(session: AsyncSession) -> None:
    """
    Seed verified_products from correct_datas.xlsx.

    Excel column layout (correct_datas.xlsx):
      Col 0 → Description            (product description as it appears on POS/invoice)
      Col 1 → HSN_SAC (As per The GST)
      Col 2 → GST(As Per The GST)    e.g. "GST 18%"

    Two normalised forms are stored per row:
      description_normalized  – exact UPPERCASE (unique key)
      description_no_size     – size tokens stripped (fallback key)
    """
    if not _VERIFIED_DATA_PATH.exists():
        log.warning("seed.verified_data_missing", path=str(_VERIFIED_DATA_PATH))
        return

    result = await session.execute(select(func.count()).select_from(VerifiedProduct))
    count = result.scalar()
    if count and count > 0:
        log.info("seed.verified_already_seeded", count=count)
        return

    try:
        import pandas as pd
    except ImportError:
        log.warning("seed.pandas_not_installed")
        return

    try:
        df = pd.read_excel(_VERIFIED_DATA_PATH, sheet_name=0, header=0)
    except Exception as e:
        log.error("seed.verified_read_error", error=str(e))
        return

    # ── Resolve column positions robustly ────────────────────────────────────
    # The file has 3 columns regardless of exact header text.
    # We use positional fallback so renamed headers don't break seeding.
    cols = df.columns.tolist()

    def _find_col(candidates: list[str], position: int) -> str:
        """Return matching column name or fall back to positional index."""
        cols_lower = {c.lower(): c for c in cols}
        for cand in candidates:
            if cand.lower() in cols_lower:
                return cols_lower[cand.lower()]
        if position < len(cols):
            return cols[position]
        return None

    desc_col = _find_col(
        ["description", "product description", "product name", "item name"], 0
    )
    hsn_col = _find_col(
        ["hsn_sac (as per the gst)", "hsn_sac", "hsn as per gst",
         "hsn_as_per_gst", "hsn code", "hsn"], 1
    )
    gst_col = _find_col(
        ["gst(as per the gst)", "gst as per the gst", "gst as per gst",
         "gst_as_per_gst", "gst rate", "gst"], 2
    )

    if not desc_col or not hsn_col:
        log.error(
            "seed.verified_col_not_found",
            desc_col=desc_col, hsn_col=hsn_col,
            available=cols,
        )
        return

    log.info(
        "seed.verified_cols_resolved",
        desc=desc_col, hsn=hsn_col, gst=gst_col, total_rows=len(df),
    )

    # ── Build rows ────────────────────────────────────────────────────────────
    rows: list[VerifiedProduct] = []
    seen_exact: set[str] = set()        # guard against duplicate normalised keys

    for _, row in df.iterrows():
        raw_desc = row.get(desc_col)
        raw_hsn  = row.get(hsn_col)
        raw_gst  = row.get(gst_col) if gst_col else None

        desc = str(raw_desc).strip() if raw_desc and str(raw_desc) != 'nan' else ""
        hsn  = _clean_hsn(raw_hsn)
        gst  = _clean_gst(raw_gst)

        if not desc or not hsn:
            continue

        desc_norm    = desc.upper().strip()
        desc_no_size = _strip_sizes(desc)

        if desc_norm in seen_exact:
            continue          # keep first occurrence (most representative)
        seen_exact.add(desc_norm)

        rows.append(VerifiedProduct(
            description=desc,
            description_normalized=desc_norm,
            description_no_size=desc_no_size,
            hsn_code=hsn,
            gst_rate=gst,
        ))

    if not rows:
        log.warning("seed.verified_no_valid_rows")
        return

    # Batch insert
    BATCH = 500
    for i in range(0, len(rows), BATCH):
        session.add_all(rows[i : i + BATCH])
        await session.commit()

    log.info("seed.verified_products_done", count=len(rows))


async def _ensure_schema() -> None:
    global _SCHEMA_DONE
    if _SCHEMA_DONE:
        return

    async with _SCHEMA_LOCK:
        if _SCHEMA_DONE:
            return

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for ddl in (
                "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS hsn_chapter VARCHAR(2)",
                "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS hsn_heading VARCHAR(4)",
                "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS hsn_subheading VARCHAR(6)",
                "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS cbic_description TEXT",
                "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS parent_heading_desc TEXT",
                "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS gst_rate FLOAT",
                "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS category VARCHAR(100)",
                "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS schedule VARCHAR(150)",
                "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
            ):
                try:
                    await conn.execute(text(ddl))
                except Exception:
                    pass
            for ddl in (
                "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS source VARCHAR(50)",
            ):
                try:
                    await conn.execute(text(ddl))
                except Exception:
                    pass
        _SCHEMA_DONE = True


async def init_db():
    global _INIT_DONE
    if _INIT_DONE:
        return

    async with _INIT_LOCK:
        if _INIT_DONE:
            return

        await _ensure_schema()
        async with async_session() as session:
            await _seed_hsn_codes(session)
            await _seed_verified_products(session)
        _INIT_DONE = True


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    await _ensure_schema()
    await init_db()
    async with async_session() as session:
        yield session
