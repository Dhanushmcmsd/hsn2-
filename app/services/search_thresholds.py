"""Centralized pg_trgm / fuzzy similarity floors by code path.

Classify (GST filing) uses stricter thresholds than predict / exploratory UX.
Do not change global ``pg_trgm.similarity_threshold`` — pass explicit ``:min_sim``
per query instead.
"""
from __future__ import annotations

CLASSIFY_BRAND_SIM_THRESHOLD = 0.65
CLASSIFY_PRODUCT_SIM_THRESHOLD = 0.55
CLASSIFY_BRAND_HIGH_SIM_THRESHOLD = 0.75
CLASSIFY_PRODUCT_HIGH_SIM_THRESHOLD = 0.70

PREDICT_BRAND_SIM_THRESHOLD = 0.50
PREDICT_PRODUCT_SIM_THRESHOLD = 0.45
PREDICT_INVERTED_SIM_THRESHOLD = 0.50
PREDICT_TRGM_SIM_THRESHOLD = 0.40

# Alias token fuzzy (language_aliases expand path)
CLASSIFY_ALIAS_FUZZY_MIN_TRGM = 0.50
CLASSIFY_ALIAS_PHONETIC_MIN_TRGM = 0.45
PREDICT_ALIAS_FUZZY_MIN_TRGM = 0.50
PREDICT_ALIAS_PHONETIC_MIN_TRGM = 0.40

# brand_search verified_products.brand trigram tier
CLASSIFY_BRAND_SEARCH_TRGM = 0.65
PREDICT_BRAND_SEARCH_TRGM = 0.35

# Short brand tokens (≤4 chars) need a higher bar on classify fuzzy tiers
CLASSIFY_SHORT_BRAND_MAX_LEN = 4
CLASSIFY_SHORT_BRAND_SIM_THRESHOLD = 0.75

# Generic commodity / ambiguous short tokens — never fuzzy-brand match
SHORT_AMBIGUOUS_NON_BRAND_TERMS: frozenset[str] = frozenset({
    "MILK", "GOLD", "OIL", "RICE", "SALT", "SOAP", "TEA", "DAL", "GHEE",
    "WATER", "SUGAR", "FLOUR", "BREAD", "EGG", "EGGS", "HONEY", "BUTTER",
})

# multi_layer_search L0b brand early-exit floors (separate from brand_lookup tier mins)
MULTI_SEARCH_BRAND_EARLY_EXIT_PREDICT = 0.80
MULTI_SEARCH_BRAND_EARLY_EXIT_CLASSIFY = 0.85
MULTI_SEARCH_BRAND_EARLY_EXIT_CLASSIFY_SHORT = 0.92
MULTI_SEARCH_BRAND_EARLY_EXIT_SHORT_MAX_LEN = 4


def brand_fuzzy_min_sim(*, for_classify: bool = False) -> float:
    return CLASSIFY_BRAND_SIM_THRESHOLD if for_classify else PREDICT_BRAND_SIM_THRESHOLD


def product_fuzzy_min_sim(*, for_classify: bool = False) -> float:
    return CLASSIFY_PRODUCT_SIM_THRESHOLD if for_classify else PREDICT_PRODUCT_SIM_THRESHOLD


def brand_fuzzy_high_sim(*, for_classify: bool = False) -> float:
    return CLASSIFY_BRAND_HIGH_SIM_THRESHOLD if for_classify else 0.75


def product_fuzzy_high_sim(*, for_classify: bool = False) -> float:
    return CLASSIFY_PRODUCT_HIGH_SIM_THRESHOLD if for_classify else 0.70


def alias_fuzzy_min_trgm(*, for_classify: bool = False) -> float:
    return CLASSIFY_ALIAS_FUZZY_MIN_TRGM if for_classify else PREDICT_ALIAS_FUZZY_MIN_TRGM


def alias_phonetic_min_trgm(*, for_classify: bool = False) -> float:
    return CLASSIFY_ALIAS_PHONETIC_MIN_TRGM if for_classify else PREDICT_ALIAS_PHONETIC_MIN_TRGM


def brand_search_trgm_floor(*, for_classify: bool = False) -> float:
    return CLASSIFY_BRAND_SEARCH_TRGM if for_classify else PREDICT_BRAND_SEARCH_TRGM


def effective_brand_trgm_min(brand_token: str, *, for_classify: bool = False) -> float:
    """Raise the bar for very short brand tokens on the classify path."""
    base = brand_search_trgm_floor(for_classify=for_classify)
    if for_classify and len((brand_token or "").strip()) <= CLASSIFY_SHORT_BRAND_MAX_LEN:
        return max(base, CLASSIFY_SHORT_BRAND_SIM_THRESHOLD)
    return base


def brand_early_exit_min_score(brand_token: str, *, for_classify: bool = False) -> float:
    """Minimum brand_lookup score before multi_layer_search L0b early-exits."""
    tok = (brand_token or "").strip().upper()
    if tok in SHORT_AMBIGUOUS_NON_BRAND_TERMS:
        return 1.0
    n = len(tok)
    if for_classify:
        if n <= MULTI_SEARCH_BRAND_EARLY_EXIT_SHORT_MAX_LEN:
            return MULTI_SEARCH_BRAND_EARLY_EXIT_CLASSIFY_SHORT
        return MULTI_SEARCH_BRAND_EARLY_EXIT_CLASSIFY
    return MULTI_SEARCH_BRAND_EARLY_EXIT_PREDICT


def should_skip_brand_early_exit(
    *,
    for_classify: bool,
    detected_language: str,
    has_direct_alias_hsn: bool,
) -> bool:
    """Prefer Kerala/alias resolution over brand early-exit on classify-critical paths."""
    if not for_classify:
        return False
    if has_direct_alias_hsn:
        return True
    return detected_language in ("ml", "ml-roman")
