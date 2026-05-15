"""Postgres-side inverted index lookup using the existing ``hsn_search.search_vector``.

Self-contained: no shared state with the existing ``db_matcher`` or FAISS layers, so a
failure here does not affect any other search layer. Returns rows in the canonical
multi-layer shape::

    {"hsn_code", "description", "score", "method", "gst_rate", "category"}
"""
from __future__ import annotations

import re
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def _to_tsquery(query: str, *, prefix_last: bool = True) -> str:
    """Build a safe tsquery string from free text. Always disjunctive (OR) so we maximise recall."""
    tokens = [t for t in _TOKEN_RE.findall(query.lower()) if len(t) >= 2][:8]
    cleaned = []
    for t in tokens:
        if not re.fullmatch(r"[a-z0-9_]+", t):
            continue
        cleaned.append(t)
    if not cleaned:
        return ""
    if prefix_last and len(cleaned) >= 1:
        cleaned[-1] = f"{cleaned[-1]}:*"
    return " | ".join(cleaned)


_SEARCH_SQL = text(
    """
    SELECT
        h.hsn_code              AS hsn_code,
        h.description           AS description,
        h.gst_rate              AS gst_rate,
        h.section_code          AS section_code,
        h.hsn_chapter           AS hsn_chapter,
        ts_rank_cd(s.search_vector, q, 32) AS rank
    FROM hsn_search s
    JOIN hsn_codes  h ON h.hsn_code = s.hsn_code
    JOIN to_tsquery('simple', :tsq) q ON s.search_vector @@ q
    WHERE COALESCE(h.is_active, TRUE) = TRUE
    ORDER BY rank DESC
    LIMIT :limit
    """
)


async def search(db: AsyncSession, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    tsq = _to_tsquery(query)
    if not tsq:
        return []
    try:
        rows = (
            await db.execute(_SEARCH_SQL, {"tsq": tsq, "limit": int(limit)})
        ).mappings().all()
    except Exception as exc:
        log.warning("inverted_index.failed", error=str(exc), tsq=tsq[:60])
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        rank = float(r["rank"] or 0.0)
        # Squash ts_rank_cd (typically 0..2+) into a 0..1 confidence-friendly band.
        score = max(0.0, min(1.0, rank / (rank + 1.0)))
        out.append(
            {
                "hsn_code": r["hsn_code"],
                "description": r["description"] or "",
                "score": score,
                "method": "L2_inverted_index",
                "gst_rate": float(r["gst_rate"]) if r["gst_rate"] is not None else None,
                "category": r["section_code"],
                "chapter": r["hsn_chapter"],
            }
        )
    return out


_TRGM_SQL = text(
    """
    SELECT
        h.hsn_code,
        h.description,
        h.gst_rate,
        h.section_code,
        h.hsn_chapter,
        similarity(s.normalized_description, :q) AS sim
    FROM hsn_search s
    JOIN hsn_codes  h ON h.hsn_code = s.hsn_code
    WHERE s.normalized_description %% :q
    ORDER BY sim DESC
    LIMIT :limit
    """
)


async def fuzzy_trgm(db: AsyncSession, query: str, *, limit: int = 20, min_sim: float = 0.18) -> list[dict[str, Any]]:
    """Postgres pg_trgm fuzzy fallback against ``hsn_search.normalized_description``.

    Uses ``%`` operator (which honours ``set_limit`` / ``pg_trgm.similarity_threshold``).
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []
    try:
        await db.execute(text("SELECT set_limit(:s)"), {"s": float(min_sim)})
        rows = (
            await db.execute(_TRGM_SQL, {"q": q, "limit": int(limit)})
        ).mappings().all()
    except Exception as exc:
        log.warning("inverted_index.fuzzy_failed", error=str(exc), q=q[:60])
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        sim = float(r["sim"] or 0.0)
        out.append(
            {
                "hsn_code": r["hsn_code"],
                "description": r["description"] or "",
                "score": sim,
                "method": "L3_pg_trgm_fuzzy",
                "gst_rate": float(r["gst_rate"]) if r["gst_rate"] is not None else None,
                "category": r["section_code"],
                "chapter": r["hsn_chapter"],
            }
        )
    return out
