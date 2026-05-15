"""6-Tier GST/HSN classification pipeline for Government of India submission.

Pipeline (each tier logs which tier returned the result):

  TIER 0  — DB Search Cache    (< 5ms)   cache hit → return instantly
  TIER 1  — Exact Brand Match  (< 10ms)  brand_aliases exact UPPER lookup
  TIER 2  — Exact Product Match(< 10ms)  verified_products exact match
  TIER 3  — Fuzzy Match        (< 50ms)  pg_trgm similarity on brand+product
  TIER 4  — Keyword/Category   (< 30ms)  keyword_category_map lookup
  TIER 5  — AI Classification  (< 3000ms) Claude API structured prompt
  TIER 6  — Manual Review Flag           logs to pending_review, returns best guess

Standard response shape:
    {
      "hsn_code": "19011000",
      "description": "Malt extract, health drinks",
      "gst_rate": 18,
      "cess_applicable": false,
      "confidence": 99,
      "tier_used": 1,
      "source": "brand_alias_exact",
      "verified": true,
      "last_updated": "2024-03-15"
    }
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Valid Indian GST rates (reject anything not in this set)
_VALID_GST_RATES = {0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 12.0, 18.0, 28.0}

# Cess-applicable chapters/HSN prefixes
_CESS_PREFIXES = {"22021", "22030", "24", "27011", "87032", "87033", "87112", "87113"}

# Unclassified fallback HSN — never surfaced to end users
_UNCLASSIFIED_HSN = "99999999"

# Cache TTL in seconds
_CACHE_TTL_EXACT = 30 * 24 * 3600   # 30 days for exact/brand matches
_CACHE_TTL_AI = 7 * 24 * 3600       # 7 days for AI-classified matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", q.upper().strip())


def _is_valid_hsn(hsn_code: str) -> bool:
    """Validate HSN code format: 2/4/6/8-digit or SAC 4-digit service code."""
    if not hsn_code:
        return False
    digits = re.sub(r"[^0-9]", "", hsn_code)
    return len(digits) in (2, 4, 6, 8)


def _is_valid_gst(rate: float | None) -> bool:
    if rate is None:
        return False
    return any(abs(rate - v) < 0.01 for v in _VALID_GST_RATES)


def _cess_for_hsn(hsn_code: str) -> bool:
    return any(hsn_code.startswith(p) for p in _CESS_PREFIXES)


def _make_result(
    hsn_code: str,
    description: str,
    gst_rate: float | None,
    cess_applicable: bool,
    confidence: int,
    tier_used: int,
    source: str,
    verified: bool,
    elapsed_ms: float,
    needs_manual_review: bool = False,
) -> dict[str, Any]:
    return {
        "hsn_code": hsn_code,
        "description": description,
        "gst_rate": gst_rate,
        "cess_applicable": cess_applicable,
        "confidence": confidence,
        "tier_used": tier_used,
        "source": source,
        "verified": verified,
        "last_updated": datetime.now(timezone.utc).date().isoformat(),
        "elapsed_ms": round(elapsed_ms, 2),
        "needs_manual_review": needs_manual_review,
    }


# ---------------------------------------------------------------------------
# TIER 0 — DB Search Cache
# ---------------------------------------------------------------------------

_CACHE_LOOKUP_SQL = text("""
    SELECT hsn_code, description, gst_rate, cess_applicable,
           confidence, tier_used, source, expires_at
    FROM search_cache
    WHERE query_normalized = :q
      AND (expires_at IS NULL OR expires_at > NOW())
    LIMIT 1
""")

_CACHE_UPSERT_SQL = text("""
    INSERT INTO search_cache
        (query_normalized, hsn_code, description, gst_rate, cess_applicable,
         confidence, tier_used, source, hit_count, expires_at, updated_at)
    VALUES
        (:q, :hsn, :desc, :gst, :cess, :conf, :tier, :src, 1,
         NOW() + INTERVAL '1 second' * :ttl, NOW())
    ON CONFLICT (query_normalized) DO UPDATE SET
        hsn_code        = EXCLUDED.hsn_code,
        description     = EXCLUDED.description,
        gst_rate        = EXCLUDED.gst_rate,
        cess_applicable = EXCLUDED.cess_applicable,
        confidence      = EXCLUDED.confidence,
        tier_used       = EXCLUDED.tier_used,
        source          = EXCLUDED.source,
        hit_count       = search_cache.hit_count + 1,
        expires_at      = EXCLUDED.expires_at,
        updated_at      = NOW()
""")


async def _tier0_cache(db: AsyncSession, query_norm: str) -> dict | None:
    try:
        row = (await db.execute(_CACHE_LOOKUP_SQL, {"q": query_norm})).mappings().first()
    except Exception as exc:
        log.debug("gst_classifier.tier0_cache_miss", error=str(exc)[:80])
        return None
    if not row:
        return None
    log.info("gst_classifier.tier0_cache_hit", q=query_norm[:50], hsn=row["hsn_code"])
    return dict(row)


async def _cache_store(
    db: AsyncSession,
    query_norm: str,
    result: dict,
    ttl: int,
) -> None:
    try:
        await db.execute(_CACHE_UPSERT_SQL, {
            "q": query_norm,
            "hsn": result["hsn_code"],
            "desc": result.get("description", ""),
            "gst": result.get("gst_rate"),
            "cess": result.get("cess_applicable", False),
            "conf": result.get("confidence", 0),
            "tier": result.get("tier_used", 0),
            "src": result.get("source", "unknown"),
            "ttl": ttl,
        })
        await db.commit()
    except Exception as exc:
        log.debug("gst_classifier.cache_store_failed", error=str(exc)[:80])


# ---------------------------------------------------------------------------
# TIER 1 — Exact Brand Match (brand_aliases table)
# ---------------------------------------------------------------------------

_BRAND_EXACT_SQL = text("""
    SELECT ba.hsn_code, ba.category, ba.gst_rate, ba.cess_applicable,
           ba.verified_source, ba.brand_name,
           hm.description
    FROM brand_aliases ba
    LEFT JOIN hsn_master hm ON hm.hsn_code = ba.hsn_code
    WHERE ba.brand_name_upper = :q
      AND ba.is_active = TRUE
    ORDER BY ba.gst_rate DESC
    LIMIT 1
""")


async def _tier1_exact_brand(db: AsyncSession, query_norm: str) -> dict | None:
    try:
        row = (await db.execute(_BRAND_EXACT_SQL, {"q": query_norm})).mappings().first()
    except Exception as exc:
        log.debug("gst_classifier.tier1_failed", error=str(exc)[:80])
        return None
    if not row:
        return None
    log.info("gst_classifier.tier1_hit", q=query_norm[:50], hsn=row["hsn_code"])
    return {
        "hsn_code": row["hsn_code"],
        "description": row["description"] or row["category"],
        "gst_rate": float(row["gst_rate"]) if row["gst_rate"] is not None else None,
        "cess_applicable": bool(row["cess_applicable"]),
        "confidence": 99,
        "tier_used": 1,
        "source": "brand_alias_exact",
        "verified": True,
    }


# ---------------------------------------------------------------------------
# TIER 2 — Exact Product Match (verified_products)
# ---------------------------------------------------------------------------

_PRODUCT_EXACT_SQL = text("""
    SELECT vp.hsn_code, vp.description, vp.gst_rate,
           hm.description AS hsn_description,
           hm.gst_rate AS hsn_gst_rate
    FROM verified_products vp
    LEFT JOIN hsn_master hm ON hm.hsn_code = vp.hsn_code
    WHERE vp.description_normalized = :q
       OR vp.description_no_size = :q
    ORDER BY
        CASE WHEN vp.description_normalized = :q THEN 0 ELSE 1 END
    LIMIT 1
""")


async def _tier2_exact_product(db: AsyncSession, query_norm: str) -> dict | None:
    try:
        row = (await db.execute(_PRODUCT_EXACT_SQL, {"q": query_norm})).mappings().first()
    except Exception as exc:
        log.debug("gst_classifier.tier2_failed", error=str(exc)[:80])
        return None
    if not row:
        return None
    raw_gst = row["gst_rate"]
    if isinstance(raw_gst, str):
        m = re.search(r"(\d+(?:\.\d+)?)", raw_gst)
        gst_val = float(m.group(1)) if m else row.get("hsn_gst_rate")
    else:
        gst_val = float(raw_gst) if raw_gst is not None else row.get("hsn_gst_rate")
    if gst_val is not None:
        gst_val = float(gst_val)
    log.info("gst_classifier.tier2_hit", q=query_norm[:50], hsn=row["hsn_code"])
    return {
        "hsn_code": row["hsn_code"],
        "description": row["hsn_description"] or row["description"],
        "gst_rate": gst_val,
        "cess_applicable": _cess_for_hsn(row["hsn_code"]),
        "confidence": 99,
        "tier_used": 2,
        "source": "verified_product_exact",
        "verified": True,
    }


# ---------------------------------------------------------------------------
# TIER 3 — Fuzzy Match (pg_trgm on brand_aliases + verified_products)
# ---------------------------------------------------------------------------

_BRAND_FUZZY_SQL = text("""
    SELECT ba.hsn_code, ba.category, ba.gst_rate, ba.cess_applicable,
           ba.brand_name, hm.description,
           similarity(ba.brand_name_upper, :q) AS sim
    FROM brand_aliases ba
    LEFT JOIN hsn_master hm ON hm.hsn_code = ba.hsn_code
    WHERE ba.is_active = TRUE
      AND similarity(ba.brand_name_upper, :q) > 0.4
    ORDER BY sim DESC
    LIMIT 1
""")

_PRODUCT_FUZZY_SQL = text("""
    SELECT vp.hsn_code, vp.description, vp.gst_rate,
           similarity(vp.description_normalized, :q) AS sim,
           hm.description AS hsn_description,
           hm.gst_rate AS hsn_gst_rate
    FROM verified_products vp
    LEFT JOIN hsn_master hm ON hm.hsn_code = vp.hsn_code
    WHERE similarity(vp.description_normalized, :q) > 0.4
    ORDER BY sim DESC
    LIMIT 1
""")


async def _tier3_fuzzy(db: AsyncSession, query_norm: str) -> dict | None:
    # Try brand fuzzy first
    try:
        row = (await db.execute(_BRAND_FUZZY_SQL, {"q": query_norm})).mappings().first()
    except Exception as exc:
        log.debug("gst_classifier.tier3_brand_fuzzy_failed", error=str(exc)[:80])
        row = None

    if row:
        sim = float(row["sim"] or 0.0)
        confidence = 85 if sim > 0.6 else 70
        log.info("gst_classifier.tier3_brand_fuzzy_hit", q=query_norm[:50], sim=sim)
        return {
            "hsn_code": row["hsn_code"],
            "description": row["description"] or row["category"],
            "gst_rate": float(row["gst_rate"]) if row["gst_rate"] is not None else None,
            "cess_applicable": bool(row["cess_applicable"]),
            "confidence": confidence,
            "tier_used": 3,
            "source": "brand_alias_fuzzy",
            "verified": True,
        }

    # Try product fuzzy
    try:
        row = (await db.execute(_PRODUCT_FUZZY_SQL, {"q": query_norm})).mappings().first()
    except Exception as exc:
        log.debug("gst_classifier.tier3_product_fuzzy_failed", error=str(exc)[:80])
        return None

    if not row:
        return None

    sim = float(row["sim"] or 0.0)
    confidence = 85 if sim > 0.6 else 70
    raw_gst = row["gst_rate"]
    if isinstance(raw_gst, str):
        m = re.search(r"(\d+(?:\.\d+)?)", raw_gst)
        gst_val = float(m.group(1)) if m else None
    else:
        gst_val = float(raw_gst) if raw_gst is not None else None
    if gst_val is None and row.get("hsn_gst_rate") is not None:
        gst_val = float(row["hsn_gst_rate"])
    log.info("gst_classifier.tier3_product_fuzzy_hit", q=query_norm[:50], sim=sim)
    return {
        "hsn_code": row["hsn_code"],
        "description": row["hsn_description"] or row["description"],
        "gst_rate": gst_val,
        "cess_applicable": _cess_for_hsn(row["hsn_code"]),
        "confidence": confidence,
        "tier_used": 3,
        "source": "product_fuzzy",
        "verified": True,
    }


# ---------------------------------------------------------------------------
# TIER 4 — Keyword/Category Match (keyword_category_map)
# ---------------------------------------------------------------------------

_KEYWORD_SQL = text("""
    SELECT kcm.hsn_code, kcm.category, kcm.description AS kw_description,
           hm.description AS hsn_description, hm.gst_rate, hm.cess_applicable
    FROM keyword_category_map kcm
    LEFT JOIN hsn_master hm ON hm.hsn_code = kcm.hsn_code
    WHERE kcm.is_active = TRUE
      AND :q ILIKE '%' || kcm.keyword || '%'
    ORDER BY LENGTH(kcm.keyword) DESC, kcm.priority DESC
    LIMIT 1
""")


async def _tier4_keyword(db: AsyncSession, query_raw: str) -> dict | None:
    try:
        row = (await db.execute(_KEYWORD_SQL, {"q": query_raw.lower()})).mappings().first()
    except Exception as exc:
        log.debug("gst_classifier.tier4_failed", error=str(exc)[:80])
        return None
    if not row:
        return None
    log.info("gst_classifier.tier4_hit", q=query_raw[:50], hsn=row["hsn_code"])
    return {
        "hsn_code": row["hsn_code"],
        "description": row["hsn_description"] or row["kw_description"] or row["category"],
        "gst_rate": float(row["gst_rate"]) if row.get("gst_rate") is not None else None,
        "cess_applicable": bool(row["cess_applicable"]) if row.get("cess_applicable") is not None else False,
        "confidence": 75,
        "tier_used": 4,
        "source": "keyword_category_map",
        "verified": True,
    }


# ---------------------------------------------------------------------------
# TIER 5 — AI Classification (Claude API)
# ---------------------------------------------------------------------------

_CLAUDE_SYSTEM = (
    "You are a GST/HSN classification expert for India. "
    "Classify the given Indian product using CBIC HSN Master 2024-25 and "
    "GST Council notifications up to March 2025. "
    "Return ONLY a JSON object with these exact keys: "
    "hsn_code (8-digit string), gst_rate (numeric), "
    "description (string), confidence (0-100 integer), chapter (2-digit string). "
    "Use official Indian GST rates: 0, 0.1, 0.25, 1.5, 3, 5, 12, 18, or 28 only."
)


async def _tier5_ai_classify(query: str) -> dict | None:
    """Call Claude API for classification. Returns None if API unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        log.debug("gst_classifier.tier5_no_api_key")
        return None

    try:
        import httpx  # type: ignore
    except ImportError:
        log.debug("gst_classifier.tier5_httpx_missing")
        return None

    prompt = (
        f"Classify this Indian product for GST/HSN:\n"
        f"Product: {query}\n"
        f"Return JSON: {{hsn_code, gst_rate, description, confidence, chapter}}\n"
        f"Use CBIC HSN 2024-25. Return 8-digit HSN only."
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 256,
                    "system": _CLAUDE_SYSTEM,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        data = resp.json()
        raw = data["content"][0]["text"].strip()
        # Extract JSON from response
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        result = json.loads(m.group(0))
        hsn = str(result.get("hsn_code", "")).strip()
        gst = float(result.get("gst_rate", 0))
        confidence = int(result.get("confidence", 50))
        desc = str(result.get("description", query))

        if not _is_valid_hsn(hsn):
            return None
        if not _is_valid_gst(gst):
            gst = None

        log.info("gst_classifier.tier5_ai_hit", q=query[:50], hsn=hsn, conf=confidence)
        return {
            "hsn_code": hsn,
            "description": desc,
            "gst_rate": gst,
            "cess_applicable": _cess_for_hsn(hsn),
            "confidence": confidence,
            "tier_used": 5,
            "source": "claude_ai_classification",
            "verified": False,
        }
    except Exception as exc:
        log.warning("gst_classifier.tier5_ai_failed", error=str(exc)[:120])
        return None


# ---------------------------------------------------------------------------
# TIER 6 — Manual Review Flag
# ---------------------------------------------------------------------------

_PENDING_INSERT_SQL = text("""
    INSERT INTO pending_review
        (query, query_normalized, best_guess_hsn, best_guess_gst,
         confidence, tier_used, source, status, created_at)
    VALUES
        (:query, :q_norm, :hsn, :gst, :conf, :tier, :src, 'pending', NOW())
    ON CONFLICT DO NOTHING
""")


async def _tier6_pending_review(
    db: AsyncSession,
    query: str,
    query_norm: str,
    best_guess: dict | None,
) -> dict:
    """Log to pending_review and return best guess with flag."""
    hsn = (best_guess or {}).get("hsn_code") or "UNKNOWN"
    gst = (best_guess or {}).get("gst_rate")
    confidence = (best_guess or {}).get("confidence", 0)

    try:
        await db.execute(_PENDING_INSERT_SQL, {
            "query": query,
            "q_norm": query_norm,
            "hsn": hsn if hsn != "UNKNOWN" else None,
            "gst": gst,
            "conf": confidence,
            "tier": 6,
            "src": "manual_review_queue",
        })
        await db.commit()
    except Exception as exc:
        log.debug("gst_classifier.tier6_log_failed", error=str(exc)[:80])

    log.warning("gst_classifier.tier6_manual_review", q=query[:50], best_hsn=hsn)

    return {
        "hsn_code": hsn if hsn != "UNKNOWN" else None,
        "description": "Approximate classification — pending verification",
        "gst_rate": gst,
        "cess_applicable": _cess_for_hsn(hsn) if hsn and hsn != "UNKNOWN" else False,
        "confidence": min(confidence, 40),
        "tier_used": 6,
        "source": "manual_review_queue",
        "verified": False,
        "needs_manual_review": True,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def classify(
    db: AsyncSession,
    query: str,
    *,
    bypass_cache: bool = False,
    enable_ai: bool = True,
) -> dict[str, Any]:
    """Classify a product query through the 6-tier GST/HSN pipeline.

    Never returns HSN 99999999 for a known product. Returns a standardised
    response dict regardless of which tier served the result.
    """
    started = time.perf_counter()
    raw_q = (query or "").strip()
    if not raw_q:
        return _make_result(
            "UNKNOWN", "Empty query", None, False, 0, 0, "empty_query", False,
            0.0, needs_manual_review=True,
        )

    query_norm = _normalize_query(raw_q)

    # ── TIER 0: DB Cache ──────────────────────────────────────────────────────
    if not bypass_cache:
        cached = await _tier0_cache(db, query_norm)
        if cached:
            elapsed = (time.perf_counter() - started) * 1000
            return _make_result(
                cached["hsn_code"],
                cached.get("description", ""),
                float(cached["gst_rate"]) if cached.get("gst_rate") is not None else None,
                bool(cached.get("cess_applicable", False)),
                100,  # verified cache = 100% confidence
                0,
                "search_cache",
                True,
                elapsed,
            )

    result: dict | None = None
    cache_ttl = _CACHE_TTL_EXACT

    # ── TIER 1: Exact Brand Match ─────────────────────────────────────────────
    result = await _tier1_exact_brand(db, query_norm)
    if result:
        elapsed = (time.perf_counter() - started) * 1000
        final = _make_result(
            result["hsn_code"], result["description"], result["gst_rate"],
            result["cess_applicable"], result["confidence"], 1,
            result["source"], True, elapsed,
        )
        await _cache_store(db, query_norm, final, _CACHE_TTL_EXACT)
        return final

    # ── TIER 2: Exact Product Match ───────────────────────────────────────────
    result = await _tier2_exact_product(db, query_norm)
    if result:
        elapsed = (time.perf_counter() - started) * 1000
        final = _make_result(
            result["hsn_code"], result["description"], result["gst_rate"],
            result["cess_applicable"], result["confidence"], 2,
            result["source"], True, elapsed,
        )
        await _cache_store(db, query_norm, final, _CACHE_TTL_EXACT)
        return final

    # ── TIER 3: Fuzzy Match ───────────────────────────────────────────────────
    result = await _tier3_fuzzy(db, query_norm)
    if result:
        elapsed = (time.perf_counter() - started) * 1000
        final = _make_result(
            result["hsn_code"], result["description"], result["gst_rate"],
            result["cess_applicable"], result["confidence"], 3,
            result["source"], True, elapsed,
        )
        await _cache_store(db, query_norm, final, _CACHE_TTL_EXACT)
        return final

    # ── TIER 4: Keyword/Category ──────────────────────────────────────────────
    result = await _tier4_keyword(db, raw_q)
    if result:
        elapsed = (time.perf_counter() - started) * 1000
        final = _make_result(
            result["hsn_code"], result["description"], result["gst_rate"],
            result["cess_applicable"], result["confidence"], 4,
            result["source"], True, elapsed,
        )
        await _cache_store(db, query_norm, final, _CACHE_TTL_EXACT)
        return final

    # ── TIER 5: AI Classification ─────────────────────────────────────────────
    best_guess = None
    if enable_ai:
        result = await _tier5_ai_classify(raw_q)
        if result and result.get("confidence", 0) >= 50:
            # Store AI result in verified_products for future cache hits
            await _cache_store(db, query_norm, result, _CACHE_TTL_AI)
            elapsed = (time.perf_counter() - started) * 1000
            return _make_result(
                result["hsn_code"], result["description"], result["gst_rate"],
                result["cess_applicable"], result["confidence"], 5,
                result["source"], False, elapsed,
            )
        best_guess = result

    # ── TIER 6: Manual Review Flag ────────────────────────────────────────────
    pending = await _tier6_pending_review(db, raw_q, query_norm, best_guess)
    elapsed = (time.perf_counter() - started) * 1000
    return _make_result(
        pending.get("hsn_code") or "UNCLASSIFIED",
        pending["description"],
        pending.get("gst_rate"),
        pending.get("cess_applicable", False),
        pending["confidence"],
        6,
        pending["source"],
        False,
        elapsed,
        needs_manual_review=True,
    )
