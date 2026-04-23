from __future__ import annotations

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.schemas import HSNRow
from app.utils.cache import get_cache, set_cache

router = APIRouter(tags=["hsn"])
log = structlog.get_logger()

_HSN_COLUMN_CACHE: dict[str, bool] = {}


def normalize_hsn(code: str) -> str:
    digits = re.sub(r"[^0-9]", "", str(code or "").strip())
    return digits.zfill(8) if digits else str(code or "").strip()


def _build_full_description(
    hsn_code: str,
    description: str,
    parent_heading_desc: str | None,
    cbic_description: str | None,
) -> str:
    if cbic_description and cbic_description.strip():
        return cbic_description.strip()

    desc_clean = (description or "").strip()
    if parent_heading_desc and parent_heading_desc.strip():
        parent = parent_heading_desc.strip().rstrip(";:,")
        child = desc_clean.lstrip("- ")
        if parent.lower() not in child.lower():
            return f"{parent} — {child}"

    return desc_clean


def _extract_chapter_info(hsn_code: str) -> dict[str, str | None]:
    code = re.sub(r"[^0-9]", "", str(hsn_code or ""))
    return {
        "chapter": code[:2] if len(code) >= 2 else None,
        "heading": code[:4] if len(code) >= 4 else None,
    }


async def _has_column(db: AsyncSession, column_name: str) -> bool:
    cached = _HSN_COLUMN_CACHE.get(column_name)
    if cached is not None:
        return cached
    try:
        await db.execute(text(f"SELECT {column_name} FROM hsn_codes LIMIT 0"))
        _HSN_COLUMN_CACHE[column_name] = True
    except Exception:
        _HSN_COLUMN_CACHE[column_name] = False
    return _HSN_COLUMN_CACHE[column_name]


@router.get("/hsn/{code}", response_model=HSNRow)
async def get_by_code(code: str, db: AsyncSession = Depends(get_db)):
    normalized_code = normalize_hsn(code)
    cached = await get_cache(f"hsn:{normalized_code}")
    if cached:
        return cached

    has_cbic_description = await _has_column(db, "cbic_description")
    has_parent_heading = await _has_column(db, "parent_heading_desc")
    has_category = await _has_column(db, "category")
    has_gst_rate = await _has_column(db, "gst_rate")
    has_section = await _has_column(db, "schedule")

    select_parts = [
        "h.hsn_code",
        "h.description",
        "h.cbic_description" if has_cbic_description else "NULL AS cbic_description",
        "h.parent_heading_desc" if has_parent_heading else "NULL AS parent_heading_desc",
        "COALESCE(h.gst_rate, 0) AS gst_rate" if has_gst_rate else "0 AS gst_rate",
        "h.category" if has_category else "NULL AS category",
        "h.schedule" if has_section else "NULL AS section",
    ]

    where_parts = ["h.hsn_code = :code"]
    if await _has_column(db, "is_active"):
        where_parts.append("h.is_active = TRUE")

    result = await db.execute(
        text(f"""
            SELECT {", ".join(select_parts)}
            FROM hsn_codes h
            WHERE {" AND ".join(where_parts)}
            LIMIT 1
        """),
        {"code": normalized_code},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"HSN code {code!r} not found")

    chapter_info = _extract_chapter_info(row.hsn_code)
    full_description = _build_full_description(
        row.hsn_code,
        row.description,
        row.parent_heading_desc,
        row.cbic_description,
    )

    data = {
        "hsn_code": normalize_hsn(row.hsn_code),
        "description": row.description,
        "full_description": full_description,
        "gst_rate": float(row.gst_rate or 0),
        "category": row.category,
        "chapter": chapter_info["chapter"],
        "heading": chapter_info["heading"],
        "section": row.section,
    }
    await set_cache(f"hsn:{normalized_code}", data)
    return data
