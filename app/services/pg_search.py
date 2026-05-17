"""
pg_search.py — PostgreSQL-native HSN search pipeline.

Replaces FAISS + sentence-transformers with 4 pure-SQL layers:
  Layer 1: Exact match on verified_products (description_normalized / description_no_size)
  Layer 2: pg_trgm trigram similarity on verified_products
  Layer 3: tsvector full-text search on hsn_codes
  Layer 4: pg_trgm trigram similarity on hsn_codes (broad fallback)

Zero model loading — instant cold start.
Requires pg_trgm extension (enabled by the Alembic migration in Problem 6).
"""
from __future__ import annotations

import re
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


def _is_postgres_db(db: AsyncSession) -> bool:
    try:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            return True
    except Exception:
        pass
    try:
        from app.config import settings
        return "postgresql" in (settings.DATABASE_URL or "").lower()
    except Exception:
        return False


async def keyword_hsn_search(db: AsyncSession, keywords: list[str]) -> dict[str, Any] | None:
    """
    Search hsn_master.description using extracted product-type keywords.
    Postgres + pg_trgm only; returns None on SQLite or when extension is missing.
    """
    if not keywords or not _is_postgres_db(db):
        log.debug("keyword_hsn_search.skipped", reason="sqlite_or_empty")
        return None

    from app.services.classifier_layers import enrich_tax_metadata

    query_str = " ".join(keywords)
    sql = text("""
        SELECT hm.hsn_code, hm.description, hm.gst_rate, hm.cess_applicable,
               similarity(lower(hm.description), lower(:q)) AS sim
        FROM hsn_master hm
        WHERE hm.is_active IS NOT FALSE
          AND length(hm.hsn_code) = 8
          AND similarity(lower(hm.description), lower(:q)) > 0.25
        ORDER BY sim DESC
        LIMIT 5
    """)

    rows: list[Any] = []
    try:
        rows = (await db.execute(sql, {"q": query_str})).mappings().all()
    except Exception as exc:
        log.debug("keyword_hsn_search.failed", error=str(exc)[:120])
        return None

    if not rows and len(keywords) > 1:
        for kw in keywords:
            try:
                rows = (await db.execute(sql, {"q": kw})).mappings().all()
                if rows:
                    break
            except Exception:
                continue

    if not rows:
        return None

    best = rows[0]
    sim = float(best.get("sim") or 0.0)
    if sim >= 0.7:
        confidence = 82
    elif sim >= 0.5:
        confidence = 75
    elif sim >= 0.35:
        confidence = 68
    else:
        confidence = 60

    base: dict[str, Any] = {
        "hsn_code": best["hsn_code"],
        "description": best.get("description") or query_str,
        "gst_rate": float(best["gst_rate"]) if best.get("gst_rate") is not None else None,
        "cess_applicable": bool(best.get("cess_applicable")),
        "confidence": confidence,
        "tier_used": 5,
        "source": "keyword_hsn_search",
        "verified": confidence >= 70,
        "matched_layer": "L5_keyword_fallback",
        "matched_source_table": "hsn_master",
        "code_kind": "HSN",
        "trust_level": "keyword_inferred",
        "alternates": [
            {
                "hsn_code": r["hsn_code"],
                "description": r.get("description"),
                "score": float(r.get("sim") or 0),
            }
            for r in rows[1:4]
            if r.get("hsn_code")
        ],
        "review_required": confidence < 70,
    }

    try:
        return await enrich_tax_metadata(db, best["hsn_code"], partial=base)
    except Exception:
        return base

_SIZE_RE = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|'
    r'PC|PCS|NOS|NO|N|P|MG|OZ|LB|TAB|TABS|CAPS|CAP)\b'
    r'|\b\d+\s*X\s*\d+\b|\b\d+\s*\+\s*\d+\b|\b\d+[SGNP]\b|\b\d+\b',
    re.IGNORECASE,
)

def _strip(text_val: str) -> str:
    t = _SIZE_RE.sub(' ', text_val.upper())
    t = re.sub(r'[^A-Z\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def _tsquery_safe(query: str) -> str:
    """Convert free text to a safe plainto_tsquery-compatible string."""
    tokens = re.findall(r'[a-zA-Z]{2,}', query.lower())[:8]
    return ' '.join(tokens) if tokens else query[:60]


async def search(
    db: AsyncSession,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.20,
) -> list[dict]:
    """
    Run all 4 layers in order; return as soon as a layer finds a result
    above the layer's threshold. Falls through to the next layer on miss.
    Returns list of result dicts in the canonical predict shape.
    """
    q_upper = query.upper().strip()
    q_stripped = _strip(q_upper)
    q_ts = _tsquery_safe(query)

    # ── Layer 1: Exact verified product match ─────────────────────────────
    try:
        rows = (await db.execute(text("""
            SELECT description, hsn_code, gst_rate, 1.0 AS score, 'pg_exact' AS method
            FROM verified_products
            WHERE description_normalized = :q
               OR description_no_size    = :qs
            ORDER BY LENGTH(description_normalized) ASC
            LIMIT :k
        """), {"q": q_upper, "qs": q_stripped, "k": top_k})).mappings().all()

        if rows and float(rows[0]["score"]) >= 0.90:
            return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        log.warning("pg_search.layer1_failed", error=str(exc))

    # ── Layer 2: Trigram similarity on verified_products ──────────────────
    try:
        rows = (await db.execute(text("""
            SELECT description, hsn_code, gst_rate,
                   GREATEST(
                       similarity(description_normalized, :q),
                       similarity(description_no_size,    :qs)
                   ) AS score,
                   'pg_trgm_verified' AS method
            FROM verified_products
            WHERE similarity(description_normalized, :q)  > :min
               OR similarity(description_no_size,    :qs) > :min
            ORDER BY score DESC
            LIMIT :k
        """), {"q": q_upper, "qs": q_stripped, "min": min_score, "k": top_k})).mappings().all()

        if rows and float(rows[0]["score"]) >= 0.35:
            return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        log.warning("pg_search.layer2_failed", error=str(exc))

    # ── Layer 3: tsvector FTS on hsn_codes ────────────────────────────────
    try:
        rows = (await db.execute(text("""
            SELECT h.description, h.hsn_code, h.gst_rate,
                   ts_rank_cd(
                       to_tsvector('english', h.description),
                       plainto_tsquery('english', :qt),
                       32
                   ) AS score,
                   'pg_fts_hsn' AS method
            FROM hsn_codes h
            WHERE to_tsvector('english', h.description)
                  @@ plainto_tsquery('english', :qt)
              AND COALESCE(h.is_active, TRUE) = TRUE
            ORDER BY score DESC
            LIMIT :k
        """), {"qt": q_ts, "k": top_k})).mappings().all()

        if rows and float(rows[0]["score"]) > 0.0:
            results = []
            for r in rows:
                d = dict(r)
                raw = float(d["score"] or 0.0)
                d["score"] = round(min(1.0, raw / (raw + 0.5)), 3)
                results.append(_row_to_dict(d))
            if results[0]["score"] >= 0.25:
                return results
    except Exception as exc:
        log.warning("pg_search.layer3_failed", error=str(exc))

    # ── Layer 4: Broad trigram fallback on hsn_codes ──────────────────────
    try:
        rows = (await db.execute(text("""
            SELECT description, hsn_code, gst_rate,
                   similarity(description, :q) AS score,
                   'pg_trgm_hsn' AS method
            FROM hsn_codes
            WHERE similarity(description, :q) > :min
              AND COALESCE(is_active, TRUE) = TRUE
            ORDER BY score DESC
            LIMIT :k
        """), {"q": query, "min": min_score * 0.8, "k": top_k})).mappings().all()

        if rows:
            return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        log.warning("pg_search.layer4_failed", error=str(exc))

    return []


def _row_to_dict(r) -> dict:
    d = dict(r) if not isinstance(r, dict) else r
    gst = d.get("gst_rate")
    try:
        gst_float = float(gst) if gst is not None else None
    except (TypeError, ValueError):
        m = re.search(r'(\d+(?:\.\d+)?)', str(gst or ''))
        gst_float = float(m.group(1)) if m else None
    return {
        "hsn_code":    str(d.get("hsn_code", "") or "").strip().zfill(8),
        "description": str(d.get("description", "") or ""),
        "gst_rate":    gst_float,
        "score":       round(float(d.get("score", 0.0) or 0.0), 4),
        "method":      str(d.get("method", "pg_search")),
        "source":      "pg_search",
    }
