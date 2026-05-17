"""Derived in-memory maps from data/kerala_retail_aliases.json (single source of truth).

Logic-only overrides live in *_MANUAL_* dicts below; everything else is built at
import/load time from the JSON corpus via kerala_corpus_hints._load_corpus_raw().

Compliance policies (Malayalam script canonical, ambiguous standalone, curated
override precedence, conservative duplicates) are documented in
docs/KERALA_SEARCH_POLICY.md and helpers in kerala_search_policy.py.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.services.kerala_corpus_hints import _load_corpus_raw

_MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")

# Invoice/OCR shorthand not worth encoding as corpus rows (logic-driven).
_MANUAL_ABBREV_OVERRIDES: dict[str, str] = {}

# Roman transliterations that must win over corpus or fill gaps (rare).
_MANUAL_TRANSLIT_OVERRIDES: dict[str, str] = {
    "tomato": "tomato fresh vegetable",
    "beetroot": "beetroot red vegetable",
    "kodampuli": "gamboge kodampuli garcinia",
    "kudampuli": "gamboge kokum kodampuli",
}

# Joined OCR forms kept when corpus row missing (corpus ocr_variant rows preferred).
_MANUAL_JOINED_FORMS: tuple[tuple[str, str], ...] = (
    ("manjalpodi", "manjal podi"),
    ("chaayapodi", "chaya podi"),
    ("chayapodi", "chaya podi"),
    ("mulakupodi", "mulaku podi"),
    ("kaapipodi", "kaapi podi"),
    ("puttupodi", "puttu podi"),
    ("appampodi", "appam podi"),
    ("ragipodi", "ragi podi"),
    ("vellachenna", "velichenna"),
    ("nendranchips", "nendran chips"),
    ("ethakkachips", "ethakka chips"),
    ("sharkkaraupperi", "sharkkara upperi"),
    ("kadalamavu", "kadala mavu"),
    ("thuvaraparippu", "thuvara parippu"),
    ("mattaari", "matta ari"),
    # "pachari" omitted — PACHARI is a packaged rice brand in client catalogs;
    # splitting to "pacha ari" breaks verified_products exact match.
    ("nadanari", "nadan ari"),
    ("chemmeenachar", "chemmeen achar"),
    ("unakkamulaku", "unakka mulaku"),
    ("idiyappampodi", "idiyappam podi"),
    ("idlyappampodi", "idly appam podi"),
    ("idlyappam", "idly appam"),
    ("gothambupodi", "gothambu podi"),
    ("sambarpodi", "sambar podi"),
    ("rasampodi", "rasam podi"),
    ("mallipodi", "malli podi"),
    ("puliinji", "puli inji"),
    ("injipuli", "inji puli"),
    ("mangaachar", "manga achar"),
)

# Curated brand+product HSN combos — small set; do not bulk-add to brand_aliases.
_MANUAL_BRAND_PRODUCT_ALIASES: dict[str, dict[str, Any]] = {
    "EASTERN MANJAL PODI": {
        "search_terms": ["eastern turmeric powder manjal podi"],
        "hsn_code": "09103030",
        "gst_rate": 5,
        "description": "Eastern turmeric powder manjal podi",
        "confidence": 0.91,
        "category": "kerala_brand",
    },
    "NIRAPARA PUTTU PODI": {
        "search_terms": ["nirapara puttu rice flour"],
        "hsn_code": "11023000",
        "gst_rate": 5,
        "description": "Nirapara puttu podi",
        "confidence": 0.9,
        "category": "kerala_brand",
    },
    "DOUBLE HORSE APPAM PODI": {
        "search_terms": ["double horse appam rice flour"],
        "hsn_code": "11029090",
        "gst_rate": 5,
        "description": "Double Horse appam podi",
        "confidence": 0.9,
        "category": "kerala_brand",
    },
}

# Standalone ambiguous roman/ml tokens: phrase-level only in expansion (priority < 50 in JSON).
# Broad single-token aliases are intentionally NOT added — context matters for HSN.
_AMBIGUOUS_STANDALONE_NOTE = "ambiguous standalone"


def _priority(row: dict) -> int:
    return int(row.get("priority", 100))


def _is_ambiguous_row(row: dict) -> bool:
    if _priority(row) < 50:
        return True
    notes = (row.get("notes") or "").lower()
    return _AMBIGUOUS_STANDALONE_NOTE in notes


@lru_cache(maxsize=1)
def _standalone_term_priority_flags() -> dict[str, tuple[int, bool]]:
    """Per single-token term: (min_priority, any_ambiguous_flag)."""
    flags: dict[str, list[tuple[int, bool]]] = {}
    for row in _load_corpus_raw():
        term = (row.get("original_term") or "").strip().lower()
        if not term or " " in term or _MALAYALAM_RE.search(term):
            continue
        flags.setdefault(term, []).append((_priority(row), _is_ambiguous_row(row)))
    out: dict[str, tuple[int, bool]] = {}
    for term, entries in flags.items():
        min_pri = min(p for p, _ in entries)
        any_amb = any(a for _, a in entries)
        out[term] = (min_pri, any_amb)
    return out


@lru_cache(maxsize=1)
def corpus_ambiguous_standalone_tokens() -> frozenset[str]:
    """Uppercase tokens that must not drive standalone exact HSN or strong translit."""
    from app.services.kerala_search_policy import _HINT_ONLY_ABBREV_KEYS

    tokens: set[str] = set()
    for term, (min_pri, any_amb) in _standalone_term_priority_flags().items():
        if min_pri < 50 or any_amb:
            tokens.add(term.upper())
    tokens.update(k.upper() for k in _HINT_ONLY_ABBREV_KEYS)
    return frozenset(tokens)


def _standalone_term_is_ambiguous(term_lower: str) -> bool:
    flags = _standalone_term_priority_flags()
    if term_lower not in flags:
        return False
    min_pri, any_amb = flags[term_lower]
    return min_pri < 50 or any_amb


@lru_cache(maxsize=1)
def corpus_transliterations_map() -> dict[str, str]:
    """Roman/ml-roman token/phrase → English (excludes ambiguous standalone singles)."""
    out: dict[str, str] = {}
    for row in _load_corpus_raw():
        lang = row.get("language_code")
        if lang not in ("ml-roman", "ml"):
            continue
        term = (row.get("original_term") or "").strip().lower()
        if " " not in term and _standalone_term_is_ambiguous(term):
            continue
        if _MALAYALAM_RE.search(term):
            continue
        english = (row.get("english_term") or row.get("canonical_query") or "").strip()
        if not term or not english:
            continue
        out[term] = english.lower()
    for k, v in _MANUAL_TRANSLIT_OVERRIDES.items():
        out.setdefault(k.lower(), v.lower())
    return out


@lru_cache(maxsize=1)
def malayalam_transliterations() -> dict[str, str]:
    """Public alias for retail_preprocess backward compatibility."""
    return dict(corpus_transliterations_map())


@lru_cache(maxsize=1)
def corpus_joined_forms_tuple() -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for row in _load_corpus_raw():
        if row.get("language_code") != "ml-roman":
            continue
        notes = (row.get("notes") or "").lower()
        is_ocr = "ocr" in notes or row.get("category") == "ocr_variant"
        orig = (row.get("original_term") or "").strip().lower()
        if not orig or _MALAYALAM_RE.search(orig) or " " in orig:
            continue
        spaced = (row.get("canonical_query") or row.get("english_term") or "").lower()
        if not spaced or not is_ocr:
            continue
        pairs.append((orig, spaced))
    manual_keys = {pair[0] for pair in _MANUAL_JOINED_FORMS}
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for joined, spaced in sorted(pairs, key=lambda x: len(x[0]), reverse=True):
        if joined in seen or joined in manual_keys:
            continue
        seen.add(joined)
        unique.append((joined, spaced))
    for pair in _MANUAL_JOINED_FORMS:
        unique.append(pair)
        seen.add(pair[0])
    return tuple(sorted(unique, key=lambda x: len(x[0]), reverse=True))


@lru_cache(maxsize=1)
def corpus_derived_alias_map() -> dict[str, dict[str, Any]]:
    """HSN alias entries from corpus rows (priority >= 50, has hsn_code). Curated map wins on merge."""
    out: dict[str, dict[str, Any]] = {}
    for row in _load_corpus_raw():
        term_lower = (row.get("original_term") or "").strip().lower()
        if " " not in term_lower and _standalone_term_is_ambiguous(term_lower):
            continue
        hsn = row.get("hsn_code")
        if not hsn:
            continue
        term = (row.get("original_term") or "").strip().upper()
        if not term or _MALAYALAM_RE.search(term):
            continue
        english = (row.get("english_term") or row.get("canonical_query") or term).strip()
        digits = re.sub(r"[^0-9]", "", str(hsn))
        if len(digits) not in (4, 6, 8):
            continue
        gst = 5.0
        if digits.startswith("19") or digits.startswith("21"):
            gst = 18.0
        elif digits.startswith("20"):
            gst = 12.0
        out[term] = {
            "search_terms": [english.lower()],
            "hsn_code": digits,
            "gst_rate": gst,
            "description": english[:80],
            "confidence": 0.84,
            "category": f"kerala_{row.get('category', 'corpus')}",
        }
    for key, val in _MANUAL_BRAND_PRODUCT_ALIASES.items():
        out.setdefault(key.upper(), val)
    return out


@lru_cache(maxsize=1)
def corpus_derived_food_map() -> dict[str, dict[str, str | None]]:
    """Substring food search map from corpus (supplements kerala_search.KERALA_FOOD_MAP)."""
    out: dict[str, dict[str, str | None]] = {}
    ambiguous = corpus_ambiguous_standalone_tokens()
    for row in _load_corpus_raw():
        term_lower = (row.get("original_term") or "").strip().lower()
        if " " not in term_lower and _standalone_term_is_ambiguous(term_lower):
            continue
        term = term_lower.upper()
        if not term or " " in term or term in ambiguous:
            continue
        english = (row.get("english_term") or row.get("canonical_query") or "").strip()
        if not english:
            continue
        hsn_raw = row.get("hsn_code")
        hsn = re.sub(r"[^0-9]", "", str(hsn_raw)) if hsn_raw else None
        if hsn and len(hsn) not in (4, 6, 8):
            hsn = None
        out[term] = {"search": english.lower(), "hsn": hsn}
    return out


def merge_alias_maps(
    curated: dict[str, dict[str, Any]],
    derived: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Curated entries override corpus-derived keys (see kerala_search_policy.merge_alias_maps)."""
    from app.services.kerala_search_policy import merge_alias_maps as _policy_merge

    return _policy_merge(curated, derived)


def is_ambiguous_standalone_query(query_upper: str) -> bool:
    """True when query is only a low-confidence ambiguous token (blocks exact alias)."""
    q = re.sub(r"\s+", " ", query_upper.strip().upper())
    if " " in q:
        return False
    return q in corpus_ambiguous_standalone_tokens()


@lru_cache(maxsize=1)
def corpus_maps_stats() -> dict[str, int]:
    return {
        "transliterations": len(corpus_transliterations_map()),
        "joined_forms": len(corpus_joined_forms_tuple()),
        "ambiguous_standalone": len(corpus_ambiguous_standalone_tokens()),
        "derived_alias_keys": len(corpus_derived_alias_map()),
        "derived_food_keys": len(corpus_derived_food_map()),
        "manual_brand_product_aliases": len(_MANUAL_BRAND_PRODUCT_ALIASES),
    }
