"""Brand-name search layer — resolves exact/fuzzy brand queries to HSN codes.

This layer sits BEFORE all other search tiers and is the primary fix for the
"BOOST / HORLICKS returns 99999999" problem reported in production.

Search tiers (executed in order, returns on first confident hit):

  Tier 0: Direct language_alias brand lookup (exact UPPER match)
          → populated from FMCG_BRAND_MASTER_2024 aliases with weight ≥ 1.5
  Tier 1: Exact brand column match in verified_products (case-insensitive)
          → returns most-common HSN for that brand
  Tier 2: Partial/fuzzy brand match using pg_trgm on brand column
          → handles "HORLICKS WOMENS" finding HORLICKS brand
  Tier 3: Category keyword match in description_no_size
          → catches "malt drink", "health drink", "instant noodles" etc.

Error boundary:
  - NEVER returns HSN 99999999 for a query that matches any known brand
  - If only a 99999999 result is available, raises the tier to AI fallback

Cache:
  - Brand lookups are cached in-process (LRU) to avoid repeated DB round-trips
  - TTL handled by the outer Redis layer in predict/search routes
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.search_thresholds import (
    SHORT_AMBIGUOUS_NON_BRAND_TERMS,
    effective_brand_trgm_min,
)

log = structlog.get_logger()

# Minimum similarity score to accept a brand match (predict / exploratory default)
_BRAND_TRGM_MIN_SIM = 0.35
_CATEGORY_TRGM_MIN_SIM = 0.25

# HSN code that must never be returned for a confirmed brand match
_UNCLASSIFIED_HSN = "99999999"

# Generic product/commodity words that are NOT brand names.
# brand_lookup must NOT intercept these — they must fall through to the
# full HSN search pipeline (pg_search, inverted_index, match_query, etc.)
# so that the most accurate HSN chapter is returned.
_NON_BRAND_TERMS: set[str] = {
    # Daily commodities
    "MILK", "WATER", "SALT", "SUGAR", "RICE", "WHEAT", "FLOUR", "DAL",
    "OIL", "BUTTER", "GHEE", "HONEY", "EGG", "EGGS", "BREAD",
    # Household
    "BROOM", "MOP", "BUCKET", "BRUSH", "SOAP", "CLOTH", "ROPE",
    "BAG", "BOX", "CAN", "CUP", "PLATE", "PAN", "POT",
    # Personal care
    "TOOTHBRUSH", "COMB", "RAZOR", "BLADE", "MIRROR",
    # Stationery
    "PEN", "PENCIL", "PAPER", "BOOK", "NOTEBOOK", "ERASER", "SCALE",
    # Fruits & vegetables
    "APPLE", "BANANA", "MANGO", "ONION", "POTATO", "TOMATO",
    "CARROT", "CABBAGE", "SPINACH", "LEMON", "ORANGE",
    # Grains / pulses
    "MAIZE", "CORN", "BARLEY", "SOYA", "GRAM", "LENTIL", "BEANS",
    # Misc
    "MEDICINE", "TABLET", "CAPSULE",
}

# Category keywords → HSN chapter hints
_CATEGORY_KEYWORDS: list[tuple[str, str, str]] = [
    # (keyword, description_hint, hsn_chapter)
    ("malt drink",        "malted milk food preparation",   "19"),
    ("health drink",      "malted milk food preparation",   "19"),
    ("protein drink",     "food preparation dietary",       "19"),
    ("instant noodles",   "pasta noodles cooked",           "19"),
    ("biscuit",           "biscuit wafer pastry",           "19"),
    ("toothpaste",        "preparations for oral hygiene",  "33"),
    ("toothbrush",        "brushes for oral hygiene",       "96"),
    ("shampoo",           "preparations for hair",          "33"),
    ("soap",              "soap personal care",             "34"),
    ("detergent",         "washing preparation detergent",  "34"),
    ("antiseptic",        "antiseptic disinfectant",        "38"),
    ("tablet",            "medicament pharmaceutical",      "30"),
    ("medicine",          "medicament pharmaceutical",      "30"),
    ("chips",             "potato chips snack",             "20"),
    ("soft drink",        "carbonated water beverage",      "22"),
    ("juice",             "fruit vegetable juice",          "20"),
    ("oil",               "edible oil",                     "15"),
    ("masala",            "spice mixture",                  "09"),
    ("tea",               "tea preparations",               "09"),
    ("coffee",            "coffee preparations",            "21"),
]


# ── Tier 0: Language alias direct lookup ──────────────────────────────────────

_ALIAS_BRAND_SQL = text("""
    SELECT la.hsn_code, la.english_term, la.weight,
           hc.description, hc.gst_rate
    FROM language_aliases la
    LEFT JOIN hsn_codes hc ON hc.hsn_code = la.hsn_code
    WHERE la.is_active = TRUE
      AND la.term_normalized = UPPER(:brand)
    ORDER BY la.weight DESC
    LIMIT 1
""")


async def _tier0_alias_lookup(db: AsyncSession, brand: str) -> dict | None:
    """Exact alias lookup: O(1) index scan on term_normalized."""
    try:
        row = (await db.execute(_ALIAS_BRAND_SQL, {"brand": brand.strip()})).mappings().first()
    except Exception as exc:
        log.debug("brand_search.tier0_failed", error=str(exc)[:80])
        return None

    if not row or not row["hsn_code"]:
        return None
    if row["hsn_code"] == _UNCLASSIFIED_HSN:
        return None

    gst = row["gst_rate"]
    return {
        "hsn_code": row["hsn_code"],
        "description": row["description"] or row["english_term"] or brand,
        "gst_rate": float(gst) if gst is not None else None,
        "score": min(1.0, float(row["weight"] or 1.0) / 2.0),
        "method": "L0_brand_alias",
        "source": "language_aliases",
    }


# ── Tier 1: Verified products brand column exact match ────────────────────────

_BRAND_EXACT_SQL = text("""
    SELECT vp.hsn_code,
           vp.description,
           vp.gst_rate,
           COUNT(*) AS freq
    FROM verified_products vp
    WHERE UPPER(vp.brand) = UPPER(:brand)
      AND vp.hsn_code IS NOT NULL
      AND vp.hsn_code != :bad_hsn
    GROUP BY vp.hsn_code, vp.description, vp.gst_rate
    ORDER BY freq DESC
    LIMIT 1
""")


async def _tier1_exact_brand(db: AsyncSession, brand: str) -> dict | None:
    """Exact brand column match — returns most-frequent HSN for that brand."""
    try:
        row = (
            await db.execute(_BRAND_EXACT_SQL, {"brand": brand.strip(), "bad_hsn": _UNCLASSIFIED_HSN})
        ).mappings().first()
    except Exception as exc:
        log.debug("brand_search.tier1_failed", error=str(exc)[:80])
        return None

    if not row:
        return None

    gst = row["gst_rate"]
    gst_val = _parse_gst(gst)
    return {
        "hsn_code": row["hsn_code"],
        "description": row["description"] or brand,
        "gst_rate": gst_val,
        "score": 0.95,
        "method": "L1_brand_exact",
        "source": "verified_products",
    }


# ── Tier 2: Fuzzy brand match ─────────────────────────────────────────────────

_BRAND_FUZZY_SQL = text("""
    SELECT vp.hsn_code,
           vp.description,
           vp.gst_rate,
           similarity(UPPER(vp.brand), UPPER(:brand)) AS sim,
           COUNT(*) AS freq
    FROM verified_products vp
    WHERE vp.brand IS NOT NULL
      AND vp.hsn_code != :bad_hsn
      AND similarity(UPPER(vp.brand), UPPER(:brand)) >= :min_sim
    GROUP BY vp.hsn_code, vp.description, vp.gst_rate,
             similarity(UPPER(vp.brand), UPPER(:brand))
    ORDER BY sim DESC, freq DESC
    LIMIT 1
""")


async def _tier2_fuzzy_brand(
    db: AsyncSession,
    brand: str,
    *,
    min_trgm: float,
) -> dict | None:
    """Trigram fuzzy brand match — catches partial names and minor typos."""
    try:
        await db.execute(text("SELECT set_limit(:s)"), {"s": min_trgm})
        row = (
            await db.execute(
                _BRAND_FUZZY_SQL,
                {"brand": brand.strip(), "bad_hsn": _UNCLASSIFIED_HSN, "min_sim": min_trgm},
            )
        ).mappings().first()
    except Exception as exc:
        log.debug("brand_search.tier2_failed", error=str(exc)[:80])
        return None

    if not row:
        return None

    sim = float(row["sim"] or 0.0)
    gst_val = _parse_gst(row["gst_rate"])
    return {
        "hsn_code": row["hsn_code"],
        "description": row["description"] or brand,
        "gst_rate": gst_val,
        "score": round(sim * 0.90, 3),
        "method": "L2_brand_fuzzy",
        "source": "verified_products",
    }


# ── Tier 3: Category keyword match ────────────────────────────────────────────

_CATEGORY_KEYWORD_SQL = text("""
    SELECT vp.hsn_code,
           vp.description,
           vp.gst_rate,
           COUNT(*) AS freq
    FROM verified_products vp
    WHERE vp.hsn_code IS NOT NULL
      AND vp.hsn_code != :bad_hsn
      AND LOWER(vp.description) LIKE :pattern
    GROUP BY vp.hsn_code, vp.description, vp.gst_rate
    ORDER BY freq DESC
    LIMIT 1
""")


async def _tier3_category_keyword(db: AsyncSession, query: str) -> dict | None:
    """Keyword match on description — chapter-level category detection.
    
    Only runs for multi-word queries or queries that are NOT in the
    _NON_BRAND_TERMS list. Generic single-word product names like
    'toothbrush', 'milk', 'broom' must fall through to the full HSN
    search pipeline for accurate chapter-level classification.
    """
    q_upper = query.upper().strip()
    q_words = q_upper.split()
    
    # Skip Tier-3 entirely for generic single-word commodity terms.
    # These must be classified by pg_search/inverted_index, not by a
    # keyword match that may return an unrelated verified_product row.
    if len(q_words) == 1 and q_words[0] in _NON_BRAND_TERMS:
        return None

    q_lower = query.lower()
    for keyword, _hint, _chapter in _CATEGORY_KEYWORDS:
        if keyword in q_lower:
            try:
                row = (
                    await db.execute(
                        _CATEGORY_KEYWORD_SQL,
                        {"pattern": f"%{keyword}%", "bad_hsn": _UNCLASSIFIED_HSN},
                    )
                ).mappings().first()
            except Exception as exc:
                log.debug("brand_search.tier3_failed", keyword=keyword, error=str(exc)[:80])
                continue

            if row:
                gst_val = _parse_gst(row["gst_rate"])
                return {
                    "hsn_code": row["hsn_code"],
                    "description": row["description"] or query,
                    "gst_rate": gst_val,
                    "score": 0.65,
                    "method": "L3_category_keyword",
                    "source": "verified_products",
                }
    return None


# ── Public entry point ────────────────────────────────────────────────────────


async def brand_lookup(
    db: AsyncSession,
    query: str,
    *,
    min_score: float = 0.30,
    for_classify: bool = False,
) -> dict[str, Any] | None:
    """Multi-tier brand search. Returns the first confident result or None.

    Guarantees:
      - Never returns HSN 99999999 for any brand present in language_aliases
        or in the verified_products.brand column.
      - Confidence score is always > min_score (default 0.30) for a returned hit.
      - Never intercepts generic commodity words (milk, broom, toothbrush…)
        so they route correctly through the full HSN search pipeline.

    Args:
        db: Async DB session.
        query: Raw user query string (e.g. "BOOST", "horlicks womens 500g").
        min_score: Minimum confidence threshold; results below this are discarded.

    Returns:
        Result dict or None if no confident match found.
    """
    q = (query or "").strip()
    if not q:
        return None

    # Extract primary brand token (first word before size/variant suffixes)
    brand_token = _extract_brand_token(q)

    # ── Early exit: skip brand pipeline for known non-brand commodity terms ──
    # This prevents Tier-3 category keyword matching from stealing generic
    # product names that should be classified by the HSN code search layers.
    ambiguous = _NON_BRAND_TERMS | SHORT_AMBIGUOUS_NON_BRAND_TERMS
    if brand_token.upper() in ambiguous and " " not in q.strip():
        log.debug("brand_search.non_brand_passthrough", term=brand_token)
        return None

    # Tier 0: language alias exact match (fastest — index lookup)
    result = await _tier0_alias_lookup(db, brand_token)
    if result and result["score"] >= min_score:
        log.info("brand_search.tier0_hit", brand=brand_token, hsn=result["hsn_code"])
        return result

    # Also try full query as alias (e.g. "GOOD DAY" as 2-word brand)
    if " " in q:
        two_word = " ".join(q.upper().split()[:2])
        result = await _tier0_alias_lookup(db, two_word)
        if result and result["score"] >= min_score:
            return result

    # Tier 1: exact brand column match
    result = await _tier1_exact_brand(db, brand_token)
    if result and result["score"] >= min_score:
        log.info("brand_search.tier1_hit", brand=brand_token, hsn=result["hsn_code"])
        return result

    # Tier 2: fuzzy brand match — stricter on classify; skip very short tokens unless exact hit
    min_trgm = effective_brand_trgm_min(brand_token, for_classify=for_classify)
    min_len_for_fuzzy = 5 if for_classify else 4
    if len(brand_token) >= min_len_for_fuzzy:
        result = await _tier2_fuzzy_brand(db, brand_token, min_trgm=min_trgm)
        if result and result["score"] >= min_score:
            log.info("brand_search.tier2_hit", brand=brand_token, hsn=result["hsn_code"])
            return result

    # Tier 3: category keyword match
    result = await _tier3_category_keyword(db, q)
    if result and result["score"] >= min_score:
        log.info("brand_search.tier3_hit", query=q[:40], hsn=result["hsn_code"])
        return result

    return None


def _extract_brand_token(query: str) -> str:
    """Extract the primary brand name from a query string.

    Strips size/variant suffixes (500g, 1kg, PCH, BIB, JAR, etc.) and
    returns the first meaningful token cluster as the candidate brand name.

    Examples:
      "HORLICKS JUNIOR VANILLA 500G" → "HORLICKS"
      "boost 1 kg container"         → "BOOST"
      "COLGATE TOTAL 150G"           → "COLGATE"
    """
    # Remove size patterns
    cleaned = re.sub(
        r"\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|MG|OZ|LB|PC|PCS|NOS)\b",
        "",
        query.upper(),
        flags=re.IGNORECASE,
    )
    # Remove packaging tokens
    cleaned = re.sub(
        r"\b(?:PCH|BIB|JAR|POUCH|SACHET|PACK|CONTAINER|REFILL|BOX|TIN|CAN|BTL|BOTTLE)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    tokens = [t for t in cleaned.split() if len(t) >= 2]
    return tokens[0] if tokens else query.strip()


def _parse_gst(raw: Any) -> float | None:
    """Extract numeric GST percentage from various string formats."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw > 0 else None
    m = re.search(r"(\d+(?:\.\d+)?)", str(raw))
    return float(m.group(1)) if m else None


def is_unclassified_hsn(hsn: str | None) -> bool:
    """Return True if this HSN is the catch-all unclassified placeholder."""
    return not hsn or str(hsn).strip() == _UNCLASSIFIED_HSN


async def get_confidence_for_brand(db: AsyncSession, brand: str) -> int:
    """Return a confidence score (0–100) for a brand query.

    Used to avoid returning low/0% confidence for well-known brands.
    """
    result = await brand_lookup(db, brand)
    if not result:
        return 0
    return min(100, max(0, round(result["score"] * 100)))
