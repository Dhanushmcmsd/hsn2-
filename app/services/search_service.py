"""Isolated product search layer: ranked HSN matches using DB matcher + existing HybridMatcher (FAISS)."""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import HsnCode
from app.models.schemas import SearchFilters, SearchMetadata, SearchResponse, SearchResult
from app.services.db_matcher import match_query
from app.services.matcher import get_matcher
from app.utils.cache import get_cache, set_cache

log = structlog.get_logger()


def build_search_cache_key(query: str, filters: SearchFilters | None, top_k: int) -> str:
    normalized = query.strip().lower()
    filter_payload: dict[str, Any] = {}
    if filters:
        d = filters.model_dump(exclude_none=True)
        filter_payload = d
    filter_hash = hashlib.md5(
        json.dumps(filter_payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]
    return f"search:v1:{normalized}:{top_k}:{filter_hash}"


def _highlight_description(query: str, description: str) -> str:
    if not description:
        return ""
    tokens = [t for t in re.findall(r"[a-z0-9]{3,}", query.lower()) if len(t) >= 3]
    html = description
    for t in tokens[:6]:
        pat = re.compile(re.escape(t), re.IGNORECASE)
        html = pat.sub(lambda m: f"<b>{m.group(0)}</b>", html, count=1)
    return html


def _match_type_from_method(method: str) -> str:
    m = (method or "").lower()
    if "semantic" in m:
        return "semantic"
    if "exact" in m or "verified" in m:
        return "exact"
    if "token" in m or "phrase" in m or "keyword" in m:
        return "fuzzy"
    if "prefix" in m or "like" in m:
        return "partial_code"
    return "hybrid"


def _apply_filters(rows: list[dict], filters: SearchFilters | None) -> list[dict]:
    if not filters:
        return rows
    out = rows
    if filters.min_confidence is not None:
        out = [r for r in out if float(r.get("score", 0)) >= filters.min_confidence]
    if filters.categories:
        cats = {c.lower() for c in filters.categories}
        out = [
            r
            for r in out
            if (r.get("category") or "").strip() and (r.get("category") or "").lower() in cats
        ]
    if filters.gst_rate is not None:
        fr = float(filters.gst_rate)
        out = [
            r
            for r in out
            if r.get("gst_rate") is not None and abs(float(r["gst_rate"]) - fr) < 0.01
        ]
    return out


def _rows_to_search_results(query: str, rows: list[dict]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for r in rows:
        desc = str(r.get("description", "") or "")
        results.append(
            SearchResult(
                hsn_code=str(r.get("hsn_code", "")),
                description=desc,
                score=float(r.get("score", 0.0)),
                match_type=_match_type_from_method(str(r.get("method", ""))),
                gst_rate=float(r["gst_rate"]) if r.get("gst_rate") is not None else None,
                category=r.get("category"),
                highlighted=_highlight_description(query, desc) if desc else None,
            )
        )
    return results


def _methods_used(rows: list[dict]) -> list[str]:
    seen: list[str] = []
    for r in rows:
        mt = _match_type_from_method(str(r.get("method", "")))
        if mt not in seen:
            seen.append(mt)
    return seen or ["hybrid"]


async def partial_code_prefix_search(db: AsyncSession, prefix: str, limit: int = 50) -> list[dict]:
    digits = re.sub(r"[^0-9]", "", prefix)
    if not digits or len(digits) < 2:
        return []
    stmt = (
        select(HsnCode)
        .where(HsnCode.is_active.is_(True))
        .where(HsnCode.hsn_code.startswith(digits))
        .order_by(HsnCode.hsn_code.asc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = []
    for row in res.scalars().all():
        rows.append(
            {
                "code": row.hsn_code,
                "description": row.description,
                "gst_rate": float(row.gst_rate) if row.gst_rate is not None else None,
                "category": row.category,
            }
        )
    return rows


async def search_products(
    db: AsyncSession,
    query: str,
    *,
    top_k: int = 10,
    filters: SearchFilters | None = None,
) -> SearchResponse:
    """Ranked HSN search: DB matcher first, then HybridMatcher (FAISS) via amatch."""
    t0 = time.perf_counter()
    cache_key = build_search_cache_key(query, filters, top_k)
    cached = await get_cache(cache_key)
    if cached:
        try:
            data = dict(cached)
            meta = dict(data.get("search_metadata") or {})
            meta["cache_hit"] = True
            data["search_metadata"] = meta
            return SearchResponse.model_validate(data)
        except Exception:
            log.warning("search.cache_corrupt", key=cache_key[:40])

    raw: list[dict] = []
    q = query.strip()
    cleaned_digits = re.sub(r"\s+", "", q)
    if cleaned_digits and re.fullmatch(r"\d{2,8}", cleaned_digits):
        db_rows = await partial_code_prefix_search(db, cleaned_digits, limit=max(top_k * 3, 30))
        raw = [
            {
                "hsn_code": r["code"],
                "description": r["description"],
                "score": 1.0 - (len(r["code"]) / 20.0),
                "method": "partial_code_prefix",
                "gst_rate": r.get("gst_rate"),
                "category": r.get("category"),
            }
            for r in db_rows
        ][:top_k]
    else:
        raw = await match_query(q, db, top_k=top_k)
        if not raw:
            matcher = get_matcher()
            raw = await matcher.amatch(q, top_k=top_k)

    raw = _apply_filters(raw, filters)
    raw = raw[:top_k]
    elapsed_ms = (time.perf_counter() - t0) * 1000
    results = _rows_to_search_results(q, raw)
    meta = SearchMetadata(
        total_candidates=len(raw),
        search_time_ms=round(elapsed_ms, 2),
        cache_hit=False,
        methods_used=_methods_used(raw),
    )
    resp = SearchResponse(query=q, results=results, search_metadata=meta)
    await set_cache(cache_key, resp.model_dump(), ttl=settings.SEARCH_CACHE_TTL)
    return resp


async def search_suggestions(db: AsyncSession, q: str, limit: int = 8) -> list[str]:
    """Short autocomplete strings from HSN descriptions (prefix on description)."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    stmt = (
        select(HsnCode.description)
        .where(HsnCode.is_active.is_(True))
        .where(HsnCode.description.ilike(f"{q[:80]}%"))
        .limit(limit * 3)
    )
    res = await db.execute(stmt)
    seen: set[str] = set()
    out: list[str] = []
    for desc in res.scalars().all():
        if not desc:
            continue
        s = str(desc).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s[:120])
        if len(out) >= limit:
            break
    return out
