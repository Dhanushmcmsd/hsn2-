"""Layered GST/HSN classification pipeline (backward-compatible tiers).

  TIER 0  — search_cache
  TIER 1  — L1 exact brand_aliases (+ service_master for SAC)
  TIER 2  — L2 exact verified_products
  TIER 3  — L3 curated hsn_master (8-digit goods)
  TIER 4  — keyword_category_map
  TIER 5  — L4 tariff (hsn_codes/history) → L5 fuzzy → multi_layer fallback
  TIER 6  — pending_review when confidence is below threshold

Additive response fields: matched_layer, matched_source_table, code_type,
tax_semantics, cess_rate, effective_total_tax, review_required, alternates.
"""
from __future__ import annotations

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

# Minimum confidence to return without manual-review flag (tiers 5+)
_MIN_AUTHORITATIVE_CONFIDENCE = 70


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ── Chapter-level GST rate lookup (CBIC 2024 schedule) ────────────────────────
# Mirrors the same table in hsn_master.py.  Used as a last-resort gst_rate fill.
_CHAPTER_GST_RATES: dict[str, float] = {
    "01": 0.0,  "02": 0.0,  "03": 5.0,  "04": 5.0,  "05": 0.0,
    "06": 5.0,  "07": 0.0,  "08": 0.0,  "09": 0.0,  "10": 0.0,
    "11": 0.0,  "12": 0.0,  "13": 5.0,  "14": 0.0,  "15": 5.0,
    "16": 12.0, "17": 5.0,  "18": 18.0, "19": 18.0, "20": 12.0,
    "21": 18.0, "22": 18.0, "23": 0.0,  "24": 28.0, "25": 5.0,
    "26": 5.0,  "27": 5.0,  "28": 18.0, "29": 18.0, "30": 12.0,
    "31": 5.0,  "32": 18.0, "33": 18.0, "34": 18.0, "35": 18.0,
    "36": 18.0, "37": 18.0, "38": 18.0, "39": 18.0, "40": 12.0,
    "41": 5.0,  "42": 12.0, "43": 12.0, "44": 12.0, "45": 12.0,
    "46": 12.0, "47": 12.0, "48": 12.0, "49": 12.0, "50": 5.0,
    "51": 5.0,  "52": 5.0,  "53": 5.0,  "54": 5.0,  "55": 5.0,
    "56": 5.0,  "57": 5.0,  "58": 5.0,  "59": 12.0, "60": 5.0,
    "61": 5.0,  "62": 5.0,  "63": 5.0,  "64": 12.0, "65": 12.0,
    "66": 12.0, "67": 12.0, "68": 12.0, "69": 12.0, "70": 18.0,
    "71": 3.0,  "72": 18.0, "73": 18.0, "74": 18.0, "75": 18.0,
    "76": 18.0, "77": 18.0, "78": 18.0, "79": 18.0, "80": 18.0,
    "81": 18.0, "82": 18.0, "83": 18.0, "84": 18.0, "85": 18.0,
    "86": 12.0, "87": 28.0, "88": 18.0, "89": 5.0,  "90": 12.0,
    "91": 18.0, "92": 18.0, "93": 12.0, "94": 18.0, "95": 18.0,
    "96": 18.0, "97": 12.0, "98": 5.0,  "99": 0.0,
}


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
    *,
    matched_layer: str | None = None,
    matched_source_table: str | None = None,
    code_type: str = "HSN",
    tax_semantics: str = "unknown",
    cess_rate: float | None = None,
    effective_total_tax: float | None = None,
    review_required: bool | None = None,
    rate_conflict: bool = False,
    trust_level: str | None = None,
    alternates: list[dict[str, Any]] | None = None,
    confidence_score: int | None = None,
) -> dict[str, Any]:
    review = review_required if review_required is not None else needs_manual_review
    conf = confidence_score if confidence_score is not None else confidence
    return {
        "hsn_code": hsn_code,
        "description": description,
        "gst_rate": gst_rate,
        "cess_applicable": cess_applicable,
        "cess_rate": cess_rate,
        "effective_total_tax": effective_total_tax,
        "confidence": conf,
        "confidence_score": conf,
        "tier_used": tier_used,
        "source": source,
        "verified": verified,
        "last_updated": datetime.now(timezone.utc).date().isoformat(),
        "elapsed_ms": round(elapsed_ms, 2),
        "needs_manual_review": needs_manual_review or review,
        "review_required": review,
        "matched_layer": matched_layer or _layer_name_for_tier(tier_used, source),
        "matched_source_table": matched_source_table,
        "code_type": code_type,
        "tax_semantics": tax_semantics,
        "rate_conflict": rate_conflict,
        "trust_level": trust_level,
        "alternates": alternates or [],
    }


def _layer_name_for_tier(tier_used: int, source: str) -> str:
    mapping = {
        0: "L0_cache",
        1: "L1_brand_alias",
        2: "L2_verified_product",
        3: "L3_curated_master",
        4: "L4_keyword_category",
        5: "L4_tariff_fallback" if "tariff" in source or "inverted" in source else "L5_fuzzy",
        6: "L6_pending_review",
    }
    return mapping.get(tier_used, f"tier_{tier_used}")


async def _finalize_layer_result(
    db: AsyncSession,
    partial: dict[str, Any],
    elapsed_ms: float,
    *,
    cache_query_norm: str | None = None,
    cache_ttl: int | None = None,
) -> dict[str, Any]:
    """Enrich tax metadata and build the outward API dict."""
    from app.services.classifier_layers import enrich_tax_metadata, is_sac_code, normalize_display_code

    code = partial.get("hsn_code") or ""
    enriched = await enrich_tax_metadata(db, code, partial=partial)
    review = bool(
        enriched.get("review_required")
        or enriched.get("confidence", 0) < _MIN_AUTHORITATIVE_CONFIDENCE
        and enriched.get("tier_used", 0) >= 5
    )
    display = normalize_display_code(
        enriched.get("hsn_code") or code,
        code_type=enriched.get("code_type", "HSN"),
    )
    if is_sac_code(display):
        enriched["code_type"] = "SAC"

    final = _make_result(
        display,
        enriched.get("description") or "",
        enriched.get("gst_rate"),
        bool(enriched.get("cess_applicable")),
        int(enriched.get("confidence", 0)),
        int(enriched.get("tier_used", 0)),
        enriched.get("source", "unknown"),
        bool(enriched.get("verified")),
        elapsed_ms,
        needs_manual_review=review or bool(enriched.get("rate_conflict")),
        matched_layer=enriched.get("matched_layer"),
        matched_source_table=enriched.get("matched_source_table"),
        code_type=enriched.get("code_type", "HSN"),
        tax_semantics=enriched.get("tax_semantics", "unknown"),
        cess_rate=enriched.get("cess_rate"),
        effective_total_tax=enriched.get("effective_total_tax"),
        review_required=review,
        rate_conflict=bool(enriched.get("rate_conflict")),
        trust_level=enriched.get("trust_level"),
        alternates=enriched.get("alternates"),
    )
    if cache_query_norm and cache_ttl and not final.get("needs_manual_review"):
        await _cache_store(db, cache_query_norm, final, cache_ttl)
    return final


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
           COALESCE(ba.code_kind,
             CASE WHEN length(ba.hsn_code) = 4 THEN 'SAC' ELSE 'HSN' END
           ) AS code_kind,
           hm.description AS hm_description,
           sm.description AS sm_description,
           sm.gst_rate AS sm_gst_rate
    FROM brand_aliases ba
    LEFT JOIN hsn_master hm
      ON hm.hsn_code = ba.hsn_code
     AND COALESCE(ba.code_kind, 'HSN') = 'HSN'
    LEFT JOIN service_master sm
      ON sm.sac_code = ba.hsn_code
     AND COALESCE(ba.code_kind,
           CASE WHEN length(ba.hsn_code) = 4 THEN 'SAC' ELSE 'HSN' END
         ) = 'SAC'
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
    code_kind = row.get("code_kind") or "HSN"
    desc = row.get("sm_description") or row.get("hm_description") or row["category"]
    gst = row["gst_rate"]
    if code_kind == "SAC" and row.get("sm_gst_rate") is not None:
        gst = row["sm_gst_rate"]
    log.info("gst_classifier.tier1_hit", q=query_norm[:50], hsn=row["hsn_code"], code_kind=code_kind)
    return {
        "hsn_code": row["hsn_code"],
        "description": desc,
        "gst_rate": float(gst) if gst is not None else None,
        "cess_applicable": bool(row["cess_applicable"]) if code_kind == "HSN" else False,
        "confidence": 99,
        "tier_used": 1,
        "source": "brand_alias_exact",
        "verified": True,
        "matched_layer": "L1_brand_alias",
        "matched_source_table": "service_master" if code_kind == "SAC" else "brand_aliases",
        "code_kind": code_kind,
        "trust_level": "curated",
    }


# ---------------------------------------------------------------------------
# TIER 2 — Exact Product Match (verified_products)
# ---------------------------------------------------------------------------

_PRODUCT_EXACT_SQL = text("""
    SELECT vp.hsn_code, vp.description, vp.gst_rate,
           hm.description AS hsn_description,
           hm.gst_rate AS hsn_gst_rate,
           hm.cess_applicable AS hm_cess,
           hm.cess_rate AS hm_cess_rate,
           hm.rate_semantics
    FROM verified_products vp
    LEFT JOIN hsn_master hm
      ON hm.hsn_code = vp.hsn_code
     AND COALESCE(hm.code_kind, 'HSN') = 'HSN'
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
    cess = row.get("hm_cess")
    if cess is None:
        cess = _cess_for_hsn(row["hsn_code"])
    log.info("gst_classifier.tier2_hit", q=query_norm[:50], hsn=row["hsn_code"])
    return {
        "hsn_code": row["hsn_code"],
        "description": row["hsn_description"] or row["description"],
        "gst_rate": gst_val,
        "cess_applicable": bool(cess),
        "cess_rate": float(row["hm_cess_rate"]) if row.get("hm_cess_rate") is not None else None,
        "confidence": 99,
        "tier_used": 2,
        "source": "verified_product_exact",
        "verified": True,
        "matched_layer": "L2_verified_product",
        "matched_source_table": "verified_products",
        "code_kind": "HSN",
        "trust_level": "verified",
        "tax_semantics": row.get("rate_semantics") or "unknown",
    }


# ---------------------------------------------------------------------------
# TIER 3 — Fuzzy Match (pg_trgm on brand_aliases + verified_products)
# ---------------------------------------------------------------------------

_BRAND_FUZZY_SQL = text("""
    SELECT ba.hsn_code, ba.category, ba.gst_rate, ba.cess_applicable,
           ba.brand_name,
           COALESCE(ba.code_kind,
             CASE WHEN length(ba.hsn_code) = 4 THEN 'SAC' ELSE 'HSN' END
           ) AS code_kind,
           hm.description AS hm_description,
           sm.description AS sm_description,
           similarity(ba.brand_name_upper, :q) AS sim
    FROM brand_aliases ba
    LEFT JOIN hsn_master hm
      ON hm.hsn_code = ba.hsn_code
     AND COALESCE(ba.code_kind, 'HSN') = 'HSN'
    LEFT JOIN service_master sm
      ON sm.sac_code = ba.hsn_code
     AND COALESCE(ba.code_kind,
           CASE WHEN length(ba.hsn_code) = 4 THEN 'SAC' ELSE 'HSN' END
         ) = 'SAC'
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
        code_kind = row.get("code_kind") or "HSN"
        return {
            "hsn_code": row["hsn_code"],
            "description": row.get("sm_description") or row.get("hm_description") or row["category"],
            "gst_rate": float(row["gst_rate"]) if row["gst_rate"] is not None else None,
            "cess_applicable": bool(row["cess_applicable"]) if code_kind == "HSN" else False,
            "confidence": confidence,
            "tier_used": 5,
            "source": "brand_alias_fuzzy",
            "verified": confidence >= _MIN_AUTHORITATIVE_CONFIDENCE,
            "matched_layer": "L5_fuzzy",
            "matched_source_table": "brand_aliases",
            "code_kind": code_kind,
            "trust_level": "fuzzy",
            "review_required": confidence < _MIN_AUTHORITATIVE_CONFIDENCE,
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
        "tier_used": 5,
        "source": "product_fuzzy",
        "verified": confidence >= _MIN_AUTHORITATIVE_CONFIDENCE,
        "matched_layer": "L5_fuzzy",
        "matched_source_table": "verified_products",
        "code_kind": "HSN",
        "trust_level": "fuzzy",
        "review_required": confidence < _MIN_AUTHORITATIVE_CONFIDENCE,
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
        "matched_layer": "L4_keyword_category",
        "matched_source_table": "keyword_category_map",
        "code_kind": "HSN",
        "trust_level": "curated",
    }





# ---------------------------------------------------------------------------
# TIER 5 — Multi-layer search fallback (inverted-index → pg_trgm → FAISS)
# ---------------------------------------------------------------------------

async def _tier5_multi_layer(db: AsyncSession, query: str) -> dict | None:
    """Fallback to the full multi-layer search pipeline (L2 → L3 → L4 → L5).

    Used when tiers 1-4 produce no result. This bridges the classify pipeline
    with the same inverted_index / pg_trgm / FAISS layers used by /predict.
    """
    try:
        from app.services.multi_layer_search import multi_search, EARLY_EXIT_SCORE
    except Exception:
        return None

    try:
        result = await multi_search(db, query, top_k=1, bypass_cache=True)
    except Exception as exc:
        log.warning("gst_classifier.tier5_multi_layer_failed", error=str(exc)[:120])
        return None

    if not result.results:
        return None

    best = result.results[0]
    hsn_code = (best.get("hsn_code") or "").strip()
    if not hsn_code or not _is_valid_hsn(hsn_code):
        return None

    # Never surface the unclassified sentinel code
    if hsn_code == _UNCLASSIFIED_HSN:
        return None

    score = float(best.get("score") or 0.0)
    gst_val = best.get("gst_rate")
    if gst_val is None:
        # Chapter-level fallback
        chapter = hsn_code[:2] if len(hsn_code) >= 2 else ""
        gst_val = _CHAPTER_GST_RATES.get(chapter)

    confidence = min(90, max(40, int(score * 100)))
    log.info(
        "gst_classifier.tier5_hit",
        q=query[:50], hsn=hsn_code, score=score,
        method=best.get("method", "multi_layer"),
    )
    return {
        "hsn_code": hsn_code,
        "description": best.get("description") or "",
        "gst_rate": gst_val,
        "cess_applicable": _cess_for_hsn(hsn_code),
        "confidence": confidence,
        "tier_used": 5,
        "source": best.get("method") or "multi_layer_search",
        "verified": score >= EARLY_EXIT_SCORE,
        "matched_layer": "L5_fuzzy",
        "matched_source_table": "hsn_codes",
        "code_kind": "HSN",
        "trust_level": "fuzzy",
        "review_required": confidence < _MIN_AUTHORITATIVE_CONFIDENCE,
    }

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


async def _tier5_broad_resolution(
    db: AsyncSession,
    raw_q: str,
    query_norm: str,
) -> dict[str, Any] | None:
    """L4 tariff → L5 fuzzy → multi_layer; returns best candidate (may be low confidence)."""
    from app.services.classifier_layers import layer_tariff_fallback

    result = await layer_tariff_fallback(db, raw_q)
    if result and int(result.get("confidence", 0)) >= _MIN_AUTHORITATIVE_CONFIDENCE:
        return result

    fuzzy = await _tier3_fuzzy(db, query_norm)
    if fuzzy and int(fuzzy.get("confidence", 0)) >= _MIN_AUTHORITATIVE_CONFIDENCE:
        return fuzzy

    multi = await _tier5_multi_layer(db, raw_q)
    if multi and int(multi.get("confidence", 0)) >= _MIN_AUTHORITATIVE_CONFIDENCE:
        return multi

    for candidate in (fuzzy, result, multi):
        if candidate:
            return candidate
    return None


async def classify(
    db: AsyncSession,
    query: str,
    *,
    bypass_cache: bool = False,
) -> dict[str, Any]:
    """Classify a product query through the layered GST/HSN pipeline."""
    started = time.perf_counter()
    raw_q = (query or "").strip()
    if not raw_q:
        return _make_result(
            "UNKNOWN", "Empty query", None, False, 0, 0, "empty_query", False,
            0.0, needs_manual_review=True, review_required=True,
            matched_layer="L6_pending_review",
        )

    query_norm = _normalize_query(raw_q)

    # ── L0 in-memory alias (no DB) ───────────────────────────────────────────
    from app.services.hsn_master import get_alias_hsn
    from app.services.classifier_layers import is_sac_code, normalize_display_code

    alias_code = get_alias_hsn(raw_q) or get_alias_hsn(query_norm)
    if alias_code:
        display = normalize_display_code(
            alias_code,
            code_type="SAC" if is_sac_code(alias_code) else "HSN",
        )
        elapsed = (time.perf_counter() - started) * 1000
        partial = {
            "hsn_code": display,
            "description": raw_q,
            "gst_rate": None,
            "cess_applicable": False,
            "confidence": 98,
            "tier_used": 1,
            "source": "L0_alias_dict",
            "verified": True,
            "matched_layer": "L1_brand_alias",
            "matched_source_table": "in_memory_alias",
            "trust_level": "curated",
        }
        return await _finalize_layer_result(db, partial, elapsed)

    # ── TIER 0: DB Cache ─────────────────────────────────────────────────────
    if not bypass_cache:
        cached = await _tier0_cache(db, query_norm)
        if cached:
            elapsed = (time.perf_counter() - started) * 1000
            partial = {
                "hsn_code": cached["hsn_code"],
                "description": cached.get("description", ""),
                "gst_rate": float(cached["gst_rate"]) if cached.get("gst_rate") is not None else None,
                "cess_applicable": bool(cached.get("cess_applicable", False)),
                "confidence": 100,
                "tier_used": 0,
                "source": "search_cache",
                "verified": True,
                "matched_layer": "L0_cache",
                "matched_source_table": "search_cache",
            }
            return await _finalize_layer_result(db, partial, elapsed)

    async def _try_layer(partial: dict[str, Any] | None) -> dict[str, Any] | None:
        if not partial:
            return None
        if partial.get("review_required") and int(partial.get("confidence", 0)) < _MIN_AUTHORITATIVE_CONFIDENCE:
            return None
        elapsed = (time.perf_counter() - started) * 1000
        return await _finalize_layer_result(
            db, partial, elapsed,
            cache_query_norm=query_norm,
            cache_ttl=_CACHE_TTL_EXACT,
        )

    # ── L1: Exact Brand ───────────────────────────────────────────────────────
    final = await _try_layer(await _tier1_exact_brand(db, query_norm))
    if final:
        return final

    # ── L2: Exact Verified Product ────────────────────────────────────────────
    final = await _try_layer(await _tier2_exact_product(db, query_norm))
    if final:
        return final

    # ── L3: Curated Master ──────────────────────────────────────────────────────
    from app.services.classifier_layers import layer_curated_master

    final = await _try_layer(await layer_curated_master(db, query_norm, raw_q))
    if final:
        return final

    # ── L4 keyword map (preserved) ──────────────────────────────────────────────
    final = await _try_layer(await _tier4_keyword(db, raw_q))
    if final:
        return final

    # ── L4 tariff + L5 fuzzy + multi_layer ──────────────────────────────────────
    broad = await _tier5_broad_resolution(db, raw_q, query_norm)
    if broad and not broad.get("review_required") and int(broad.get("confidence", 0)) >= _MIN_AUTHORITATIVE_CONFIDENCE:
        elapsed = (time.perf_counter() - started) * 1000
        return await _finalize_layer_result(
            db, broad, elapsed,
            cache_query_norm=query_norm,
            cache_ttl=_CACHE_TTL_EXACT,
        )

    # ── L6: Manual review (low confidence or no match) ──────────────────────────
    pending = await _tier6_pending_review(db, raw_q, query_norm, broad)
    elapsed = (time.perf_counter() - started) * 1000
    code = pending.get("hsn_code") or "UNCLASSIFIED"
    partial = {
        **pending,
        "hsn_code": code,
        "tier_used": 6,
        "matched_layer": "L6_pending_review",
        "review_required": True,
        "alternates": (broad or {}).get("alternates", []),
    }
    return await _finalize_layer_result(db, partial, elapsed)
