"""Multi-layer search orchestrator: alias -> cache -> inverted-index -> fuzzy -> FAISS.

Pipeline (each step is fully independent - failure in one layer does not abort the others):

    L0   Hindi / Malayalam / English alias + synonym expansion (in-memory)
    L0b  Brand alias lookup (early-exit when confident)
    L1a  Process-local LRU cache (zero-latency, no network)
    L1b  Redis/Upstash cache (fallback when LRU misses)
    L2   Postgres inverted-index lookup over hsn_search.search_vector (ts_rank_cd)
    L3   Postgres pg_trgm fuzzy fallback against normalized_description
    L4   FAISS semantic fallback via the existing HybridMatcher (amatch)
    L5   Direct HSN code prefix lookup (when the user types digits)
    L6   Verified-products exact / no-size match (gold dataset reuse)
    L7   Category / chapter boost (re-rank using the 11 official sections)

Optimisations vs original:
  - L1a in-memory LRU before any network I/O  -> ~0ms for repeat queries
  - verified_products lookup first in gather() -> often short-circuits
  - Per-layer timeouts tightened              -> tail-latency improvement
  - asyncio.gather() fan-out unchanged        -> no regression
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import aliases as aliases_service
from app.services import inverted_index
from app.services.brand_search import brand_lookup, is_unclassified_hsn
from app.services.in_memory_cache import lru_get, lru_set
from app.services.matcher import get_matcher
from app.utils.cache import get_cache, set_cache

log = structlog.get_logger()

# Per-layer hard timeouts (seconds)
LAYER_TIMEOUTS = {
    "inverted": settings.MULTI_SEARCH_TIMEOUT_INVERTED_MS / 1000,
    "fuzzy":    settings.MULTI_SEARCH_TIMEOUT_FUZZY_MS    / 1000,
    "faiss":    settings.MULTI_SEARCH_TIMEOUT_FAISS_MS    / 1000,
    "verified": settings.MULTI_SEARCH_TIMEOUT_VERIFIED_MS / 1000,
    "prefix":   settings.MULTI_SEARCH_TIMEOUT_PREFIX_MS   / 1000,
}

NEGATIVE_CACHE_TTL  = settings.NEG_CACHE_TTL
DEFAULT_RESULT_TTL  = settings.SEARCH_CACHE_TTL
LRU_TTL             = 300   # 5 min in-memory TTL
TOP_K_DEFAULT       = 10

# Early-exit score: if verified_products returns a result at or above this
# score we skip FAISS and pg_trgm entirely (saves 200-400 ms on every hit).
EARLY_EXIT_SCORE = 0.94


def _stable_filter_hash(filters: dict | None) -> str:
    if not filters:
        return "f-"
    payload = json.dumps(filters, sort_keys=True, default=str)
    return "f-" + hashlib.md5(payload.encode("utf-8")).hexdigest()[:10]


def build_cache_key(query: str, top_k: int, filters: dict | None) -> str:
    norm = (query or "").strip().lower()
    return f"search:multi:v2:{norm}:{top_k}:{_stable_filter_hash(filters)}"


@dataclass
class LayerTrace:
    name: str
    ms: float
    candidate_count: int
    used: bool = True
    error: str | None = None


@dataclass
class MultiSearchResult:
    query: str
    detected_language: str
    english_query: str
    expansions: list[str]
    results: list[dict[str, Any]]
    cache_hit: bool
    total_time_ms: float
    layers: list[LayerTrace] = field(default_factory=list)
    methods_used: list[str] = field(default_factory=list)
    direct_hsn_hints: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Layer implementations
# ---------------------------------------------------------------------------

async def _layer_inverted(db: AsyncSession, queries: Sequence[str], limit: int) -> list[dict]:
    seen: dict[str, dict] = {}
    for q in queries[:4]:
        rows = await inverted_index.search(db, q, limit=limit)
        for row in rows:
            key = row["hsn_code"]
            existing = seen.get(key)
            if not existing or row["score"] > existing["score"]:
                seen[key] = row
    return sorted(seen.values(), key=lambda r: r["score"], reverse=True)[:limit]


async def _layer_fuzzy(db: AsyncSession, queries: Sequence[str], limit: int) -> list[dict]:
    seen: dict[str, dict] = {}
    for q in queries[:3]:
        rows = await inverted_index.fuzzy_trgm(db, q, limit=limit, min_sim=0.18)
        for row in rows:
            key = row["hsn_code"]
            existing = seen.get(key)
            if not existing or row["score"] > existing["score"]:
                seen[key] = row
    return sorted(seen.values(), key=lambda r: r["score"], reverse=True)[:limit]


async def _layer_faiss(query: str, limit: int) -> list[dict]:
    import os

    if os.getenv("FAISS_DISABLED") == "1":
        log.info("faiss.disabled_by_env")
        return []
    try:
        matcher = get_matcher()
    except Exception as exc:
        log.warning("multi.faiss_unavailable", error=str(exc))
        return []
    rows = await matcher.amatch(query, top_k=limit)
    out: list[dict] = []
    for r in rows:
        out.append({
            "hsn_code":    str(r.get("hsn_code") or r.get("code") or ""),
            "description": r.get("description") or r.get("full_description") or "",
            "score":       float(r.get("score") or 0.0),
            "method":      "L4_faiss_semantic",
            "gst_rate":    float(r["gst_rate"]) if r.get("gst_rate") is not None else None,
            "category":    r.get("category"),
            "chapter":     r.get("chapter") or r.get("hsn_chapter"),
        })
    return out


_PREFIX_SQL = text("""
    SELECT hsn_code, description, gst_rate, section_code, hsn_chapter
    FROM hsn_codes
    WHERE COALESCE(is_active, TRUE) = TRUE
      AND hsn_code LIKE :pat
    ORDER BY hsn_code
    LIMIT :limit
""")


async def _layer_prefix(db: AsyncSession, query: str, limit: int) -> list[dict]:
    digits = re.sub(r"[^0-9]", "", query)
    if len(digits) < 2 or len(digits) > 8:
        return []
    rows = (await db.execute(_PREFIX_SQL, {"pat": digits + "%", "limit": int(limit)})).mappings().all()
    out: list[dict] = []
    for r in rows:
        score = 1.0 - (max(0, len(r["hsn_code"]) - len(digits)) * 0.05)
        out.append({
            "hsn_code":    r["hsn_code"],
            "description": r["description"] or "",
            "score":       max(0.45, score),
            "method":      "L5_prefix_code",
            "gst_rate":    float(r["gst_rate"]) if r["gst_rate"] is not None else None,
            "category":    r["section_code"],
            "chapter":     r["hsn_chapter"],
        })
    return out


_VERIFIED_SQL = text("""
    WITH q AS (SELECT UPPER(:q) AS up, regexp_replace(UPPER(:q), '[^A-Z ]+', '', 'g') AS up_no_size)
    SELECT
      v.hsn_code,
      v.description,
      v.gst_rate,
      v.brand,
      v.category,
      h.gst_rate        AS hsn_gst_rate,
      h.section_code,
      h.hsn_chapter,
      h.description     AS hsn_description,
      CASE
        WHEN v.description_normalized::text = q.up            THEN 1.0
        WHEN v.description_no_size::text    = q.up_no_size    THEN 0.94
        ELSE GREATEST(
            similarity(v.description_normalized::text, q.up),
            similarity(COALESCE(v.description_no_size, '')::text, q.up_no_size)
        )
      END AS score
    FROM verified_products v
    LEFT JOIN hsn_codes h ON h.hsn_code = v.hsn_code
    , q
    WHERE
       v.description_normalized::text = q.up
       OR v.description_no_size::text  = q.up_no_size
       OR v.description_normalized::text %% q.up
       OR v.description_no_size::text  %% q.up_no_size
    ORDER BY score DESC
    LIMIT :limit
""")


async def _layer_verified(db: AsyncSession, query: str, limit: int) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    try:
        await db.execute(text("SELECT set_limit(0.30)"))
        rows = (await db.execute(_VERIFIED_SQL, {"q": q, "limit": int(limit)})).mappings().all()
    except Exception as exc:
        log.warning("multi.verified_failed", error=str(exc), q=q[:60])
        return []
    out: list[dict] = []
    for r in rows:
        gst = r["gst_rate"]
        if isinstance(gst, str):
            digits = re.findall(r"\d+(?:\.\d+)?", gst)
            gst_val = float(digits[0]) if digits else None
        else:
            gst_val = float(gst) if gst is not None else None
        if gst_val is None and r["hsn_gst_rate"] is not None:
            gst_val = float(r["hsn_gst_rate"])
        out.append({
            "hsn_code":       r["hsn_code"],
            "description":    r["hsn_description"] or r["description"] or "",
            "score":          float(r["score"] or 0.0),
            "method":         "L6_verified_products",
            "gst_rate":       gst_val,
            "category":       r["section_code"] or r["category"],
            "chapter":        r["hsn_chapter"],
            "brand":          r["brand"],
            "raw_description": r["description"],
        })
    return out


async def _bounded(name: str, coro, timeout: float, layers: list[LayerTrace]) -> list[dict]:
    started = time.perf_counter()
    try:
        rows = await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        layers.append(LayerTrace(name=name, ms=(time.perf_counter() - started) * 1000,
                                 candidate_count=0, used=False, error="timeout"))
        return []
    except Exception as exc:
        layers.append(LayerTrace(name=name, ms=(time.perf_counter() - started) * 1000,
                                 candidate_count=0, used=False, error=str(exc)[:120]))
        return []
    layers.append(LayerTrace(name=name, ms=(time.perf_counter() - started) * 1000,
                             candidate_count=len(rows)))
    return rows


# ---------------------------------------------------------------------------
# Re-ranking & merging
# ---------------------------------------------------------------------------

_LAYER_PRIORITY = {
    "L1_cache":             0.0,
    "L6_verified_products": 0.18,
    "L2_inverted_index":    0.10,
    "L4_faiss_semantic":    0.08,
    "L3_pg_trgm_fuzzy":     0.05,
    "L5_prefix_code":       0.0,
}


def _matches_alias_hint(code: str, boost_codes: set[str]) -> bool:
    if not code or not boost_codes:
        return False
    if code in boost_codes:
        return True
    return any(code.startswith(b) for b in boost_codes if b)


def _merge(*pools: list[dict], boost_codes: set[str] | None = None) -> list[dict]:
    by_code: dict[str, dict] = {}
    boost_codes = boost_codes or set()
    for pool in pools:
        for row in pool:
            code = (row.get("hsn_code") or "").strip()
            if not code:
                continue
            adj = float(row.get("score", 0.0)) + _LAYER_PRIORITY.get(row.get("method", ""), 0.0)
            if _matches_alias_hint(code, boost_codes):
                adj += 0.07
            row["adj_score"] = adj
            existing = by_code.get(code)
            if not existing or adj > existing["adj_score"]:
                by_code[code] = row
    merged = sorted(by_code.values(), key=lambda r: r["adj_score"], reverse=True)
    for row in merged:
        row["score"] = round(min(1.0, max(0.0, row["adj_score"])), 4)
        row.pop("adj_score", None)
    return merged


def _apply_filters(rows: list[dict], filters: dict | None) -> list[dict]:
    if not filters:
        return rows
    out = rows
    if filters.get("min_confidence") is not None:
        threshold = float(filters["min_confidence"])
        out = [r for r in out if float(r.get("score", 0)) >= threshold]
    if filters.get("categories"):
        cats = {str(c).upper() for c in filters["categories"]}
        out = [r for r in out if (r.get("category") or "").upper() in cats]
    if filters.get("gst_rate") is not None:
        target = float(filters["gst_rate"])
        out = [r for r in out if r.get("gst_rate") is not None and abs(float(r["gst_rate"]) - target) < 0.01]
    if filters.get("chapter"):
        chap = str(filters["chapter"]).zfill(2)
        out = [r for r in out if str(r.get("chapter") or "").zfill(2) == chap]
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def multi_search(
    db: AsyncSession,
    query: str,
    *,
    top_k: int = TOP_K_DEFAULT,
    filters: dict | None = None,
    bypass_cache: bool = False,
    explain: bool = False,
) -> MultiSearchResult:
    started = time.perf_counter()
    layers: list[LayerTrace] = []
    raw_q = (query or "").strip()
    if not raw_q:
        return MultiSearchResult(
            query="", detected_language="en", english_query="", expansions=[],
            results=[], cache_hit=False, total_time_ms=0.0, layers=[], methods_used=[],
        )

    # -- L0 alias expansion --------------------------------------------------
    t0 = time.perf_counter()
    try:
        expanded = await aliases_service.expand_query(db, raw_q)
        layers.append(LayerTrace(name="L0_alias", ms=(time.perf_counter() - t0) * 1000,
                                 candidate_count=len(expanded.expansions)))
    except Exception as exc:
        layers.append(LayerTrace(name="L0_alias", ms=(time.perf_counter() - t0) * 1000,
                                 candidate_count=0, used=False, error=str(exc)[:120]))
        expanded = aliases_service.ExpansionResult(
            original=raw_q, detected_language="en", english_query=raw_q,
        )

    cache_key = build_cache_key(expanded.english_query or raw_q, top_k, filters)

    # -- L1a  In-process LRU cache (zero-latency) ----------------------------
    if not bypass_cache:
        lru_hit = lru_get(cache_key)
        if lru_hit and isinstance(lru_hit, dict):
            layers.append(LayerTrace(name="L1a_lru", ms=0.0, candidate_count=1))
            return MultiSearchResult(
                query=raw_q,
                detected_language=expanded.detected_language,
                english_query=expanded.english_query,
                expansions=expanded.expansions,
                results=list(lru_hit.get("results") or [])[:top_k],
                cache_hit=True,
                total_time_ms=(time.perf_counter() - started) * 1000,
                layers=layers,
                methods_used=list(lru_hit.get("methods_used") or []),
                direct_hsn_hints=expanded.direct_hsn_hints,
            )

    # -- L1b  Redis / Upstash cache ------------------------------------------
    cache_hit = False
    if not bypass_cache:
        t1 = time.perf_counter()
        try:
            cached = await asyncio.wait_for(get_cache(cache_key), timeout=0.4)
        except Exception:
            cached = None
        layers.append(LayerTrace(name="L1b_redis", ms=(time.perf_counter() - t1) * 1000,
                                 candidate_count=1 if cached else 0))
        if cached and isinstance(cached, dict):
            cache_hit = True
            lru_set(cache_key, cached, ttl=LRU_TTL)   # populate LRU for next call
            return MultiSearchResult(
                query=raw_q,
                detected_language=expanded.detected_language,
                english_query=expanded.english_query,
                expansions=expanded.expansions,
                results=list(cached.get("results") or [])[:top_k],
                cache_hit=True,
                total_time_ms=(time.perf_counter() - started) * 1000,
                layers=layers,
                methods_used=list(cached.get("methods_used") or []),
                direct_hsn_hints=expanded.direct_hsn_hints,
            )

    # -- L0b  Brand alias lookup (early-exit when confident) -----------------
    try:
        brand_hit = await brand_lookup(db, expanded.english_query or raw_q, min_score=0.80)
    except Exception:
        brand_hit = None

    if brand_hit and not is_unclassified_hsn(brand_hit.get("hsn_code")):
        result_list = [brand_hit]
        result_list[0]["layer"] = "L0b_brand_alias"
        payload_brand = {
            "results": result_list,
            "methods_used": [brand_hit.get("method", "brand_lookup")],
            "english_query": expanded.english_query,
            "detected_language": expanded.detected_language,
            "expansions": expanded.expansions,
        }
        if not bypass_cache:
            lru_set(cache_key, payload_brand, ttl=LRU_TTL)
            try:
                await set_cache(cache_key, payload_brand, ttl=DEFAULT_RESULT_TTL)
            except Exception:
                pass
        return MultiSearchResult(
            query=raw_q,
            detected_language=expanded.detected_language,
            english_query=expanded.english_query,
            expansions=expanded.expansions,
            results=result_list[:top_k],
            cache_hit=False,
            total_time_ms=round((time.perf_counter() - started) * 1000, 2),
            layers=layers,
            methods_used=[brand_hit.get("method", "brand_lookup")],
            direct_hsn_hints=expanded.direct_hsn_hints,
        )

    # -- L6 first (verified products) — run before fan-out for early-exit ----
    variants = expanded.all_text_variants()
    eng_q    = expanded.english_query or raw_q

    t_v = time.perf_counter()
    verified_rows = await _bounded(
        "L6_verified_products",
        _layer_verified(db, eng_q, top_k * 2),
        LAYER_TIMEOUTS["verified"],
        layers,
    )
    verified_ms = (time.perf_counter() - t_v) * 1000

    # Early-exit: verified hit at or above threshold -> skip heavy layers
    top_verified_score = verified_rows[0]["score"] if verified_rows else 0.0
    if top_verified_score >= EARLY_EXIT_SCORE:
        merged = _apply_filters(_merge(verified_rows), filters)
        non_unclassified = [r for r in merged if not is_unclassified_hsn(r.get("hsn_code"))]
        final = (non_unclassified or merged)[:top_k]
        methods_used = list({r.get("method", "") for r in final})
        elapsed_ms = (time.perf_counter() - started) * 1000
        payload = {
            "results": final,
            "methods_used": methods_used,
            "english_query": expanded.english_query,
            "detected_language": expanded.detected_language,
            "expansions": expanded.expansions,
        }
        if not bypass_cache:
            lru_set(cache_key, payload, ttl=LRU_TTL)
            try:
                await set_cache(cache_key, payload, ttl=DEFAULT_RESULT_TTL)
            except Exception:
                pass
        log.debug("multi.early_exit", score=top_verified_score, ms=elapsed_ms)
        return MultiSearchResult(
            query=raw_q,
            detected_language=expanded.detected_language,
            english_query=expanded.english_query,
            expansions=expanded.expansions,
            results=final,
            cache_hit=False,
            total_time_ms=round(elapsed_ms, 2),
            layers=layers,
            methods_used=methods_used,
            direct_hsn_hints=expanded.direct_hsn_hints,
        )

    # -- L2..L5 fan-out (only when verified didn't early-exit) ---------------
    inv_task    = _bounded("L2_inverted_index", _layer_inverted(db, variants, top_k * 2), LAYER_TIMEOUTS["inverted"], layers)
    fuzzy_task  = _bounded("L3_pg_trgm_fuzzy",  _layer_fuzzy(db, variants, top_k * 2),   LAYER_TIMEOUTS["fuzzy"],    layers)
    faiss_task  = _bounded("L4_faiss_semantic",  _layer_faiss(eng_q, top_k * 2),          LAYER_TIMEOUTS["faiss"],    layers)
    prefix_task = _bounded("L5_prefix_code",     _layer_prefix(db, raw_q, top_k * 3),    LAYER_TIMEOUTS["prefix"],   layers)

    inv_rows, fuzzy_rows, faiss_rows, prefix_rows = await asyncio.gather(
        inv_task, fuzzy_task, faiss_task, prefix_task
    )

    boost_codes = {h["hsn_code"] for h in expanded.direct_hsn_hints if h.get("hsn_code")}
    merged = _merge(verified_rows, prefix_rows, inv_rows, faiss_rows, fuzzy_rows,
                    boost_codes=boost_codes)
    merged = _apply_filters(merged, filters)

    non_unclassified = [r for r in merged if not is_unclassified_hsn(r.get("hsn_code"))]
    if non_unclassified:
        merged = non_unclassified
    elif brand_hit:
        merged = [brand_hit]

    final = merged[:top_k]
    methods_used = []
    for row in final:
        m = row.get("method", "")
        if m and m not in methods_used:
            methods_used.append(m)

    elapsed_ms = (time.perf_counter() - started) * 1000
    payload = {
        "results": final,
        "methods_used": methods_used,
        "english_query": expanded.english_query,
        "detected_language": expanded.detected_language,
        "expansions": expanded.expansions,
    }
    ttl = DEFAULT_RESULT_TTL if final else NEGATIVE_CACHE_TTL
    if not bypass_cache:
        lru_set(cache_key, payload, ttl=LRU_TTL)
        try:
            await set_cache(cache_key, payload, ttl=ttl)
        except Exception:
            pass

    # ── L5 keyword fallback when no authoritative hit ─────────────────────────
    if not final:
        try:
            from app.services.normalizer import extract_product_keywords
            from app.services.pg_search import keyword_hsn_search

            keywords = extract_product_keywords(raw_q)
            if keywords:
                kw = await keyword_hsn_search(db, keywords)
                hsn_kw = (kw or {}).get("hsn_code") or ""
                digits = re.sub(r"[^0-9]", "", str(hsn_kw))
                valid_kw_hsn = len(digits) in (2, 4, 6, 8)
                if (
                    kw
                    and valid_kw_hsn
                    and not is_unclassified_hsn(hsn_kw)
                ):
                    conf = int(kw.get("confidence", 0))
                    final = [{
                        "hsn_code": kw["hsn_code"],
                        "description": kw.get("description") or raw_q,
                        "gst_rate": kw.get("gst_rate"),
                        "score": conf / 100.0,
                        "method": "keyword_hsn_search",
                        "source": "keyword_hsn_search",
                        "layer": "L5_keyword_fallback",
                    }]
                    methods_used = ["keyword_hsn_search"]
        except Exception as exc:
            log.debug("multi_layer.keyword_fallback_error", error=str(exc)[:120])

    if not final:
        try:
            import asyncio as _asyncio
            from app.services.miss_logger import log_miss as _log_miss
            from app.services.normalizer import normalize_product_name as _norm_name

            async def _bg_miss() -> None:
                try:
                    from app.models.database import async_session
                    async with async_session() as miss_db:
                        await _log_miss(miss_db, raw_q, _norm_name(raw_q))
                except Exception:
                    pass

            _asyncio.create_task(_bg_miss())
        except Exception:
            pass

    return MultiSearchResult(
        query=raw_q,
        detected_language=expanded.detected_language,
        english_query=expanded.english_query,
        expansions=expanded.expansions,
        results=final,
        cache_hit=cache_hit,
        total_time_ms=round(elapsed_ms, 2),
        layers=layers if explain else [l for l in layers if l.candidate_count or l.error],
        methods_used=methods_used,
        direct_hsn_hints=expanded.direct_hsn_hints,
    )


# ---------------------------------------------------------------------------
# Helper queries
# ---------------------------------------------------------------------------

_CATEGORIES_SQL = text("""
    SELECT
        c.category_code, c.category_name, c.section_code,
        c.chapter_range_start, c.chapter_range_end, c.display_order,
        c.official_source, c.description,
        COALESCE(stats.code_count, 0) AS code_count
    FROM category_taxonomy c
    LEFT JOIN (
        SELECT section_code, COUNT(*) AS code_count
        FROM hsn_codes
        WHERE COALESCE(is_active, TRUE) = TRUE
        GROUP BY section_code
    ) stats ON stats.section_code = c.category_code
    ORDER BY c.display_order
""")


async def list_categories(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(_CATEGORIES_SQL)).mappings().all()
    return [dict(r) for r in rows]


_BY_LANGUAGE_SQL = text("""
    WITH matched AS (
        SELECT a.term, a.english_term, a.weight, a.hsn_code AS alias_code
        FROM language_aliases a
        WHERE a.is_active = TRUE
          AND a.language = :lang
          AND (
                a.term_normalized = UPPER(:q)
             OR a.term ILIKE :ilike
             OR a.term_normalized::text %% UPPER(:q)
          )
    )
    SELECT
        h.hsn_code, h.description, h.gst_rate, h.section_code, h.hsn_chapter,
        m.term, m.english_term, m.weight
    FROM matched m
    JOIN hsn_codes h
      ON (h.hsn_code = m.alias_code OR h.hsn_code LIKE m.alias_code || '%')
    WHERE COALESCE(h.is_active, TRUE) = TRUE
    ORDER BY m.weight DESC, LENGTH(h.hsn_code) ASC
    LIMIT :limit
""")


async def search_by_language(db: AsyncSession, query: str, language: str, *, limit: int = 10) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q or language not in {"hi", "ml", "en"}:
        return []
    try:
        await db.execute(text("SELECT set_limit(0.30)"))
        rows = (await db.execute(
            _BY_LANGUAGE_SQL,
            {"q": q, "ilike": f"%{q}%", "lang": language, "limit": int(limit)},
        )).mappings().all()
    except Exception as exc:
        log.warning("multi.by_language_failed", error=str(exc), q=q[:40], lang=language)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "hsn_code":    r["hsn_code"],
            "description": r["description"],
            "gst_rate":    float(r["gst_rate"]) if r["gst_rate"] is not None else None,
            "category":    r["section_code"],
            "chapter":     r["hsn_chapter"],
            "matched_term":  r["term"],
            "english_term":  r["english_term"],
            "weight":        float(r["weight"] or 1.0),
        })
    return out


# ---------------------------------------------------------------------------
# Background warm-up
# ---------------------------------------------------------------------------

async def warmup(db: AsyncSession) -> None:
    """Called from app lifespan: pre-load alias index + ping common indexes."""
    try:
        await aliases_service.refresh(db, force=True)
    except Exception as exc:
        log.warning("multi.warmup_aliases_failed", error=str(exc))
    try:
        await db.execute(text("SELECT 1"))
        await db.execute(text("SELECT COUNT(*) FROM hsn_search WHERE hsn_code IS NOT NULL"))
    except Exception as exc:
        log.warning("multi.warmup_db_failed", error=str(exc))
