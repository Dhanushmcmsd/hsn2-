"""Load Kerala retail corpus hints for preprocess and language detection."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_CORPUS = Path(__file__).resolve().parents[2] / "data" / "kerala_retail_aliases.json"
_MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")

# Roman tokens that strongly indicate Kerala retail queries (from corpus ml-roman rows)
_KERALA_ROMAN_STOP = frozenset({
    "KG", "GM", "ML", "LT", "LTR", "PCS", "NOS", "PKT", "PACK", "BAG", "BOX",
    "EASTERN", "NIRAPARA", "DOUBLE", "HORSE", "BRU", "BOOST", "MILMA",
})


@lru_cache(maxsize=1)
def _load_corpus_raw() -> list[dict]:
    if not _CORPUS.exists():
        return []
    data = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def corpus_transliterations() -> dict[str, str]:
    """Romanized Malayalam token/phrase → English (from JSON via kerala_corpus_maps)."""
    from app.services.kerala_corpus_maps import corpus_transliterations_map

    return corpus_transliterations_map()


def corpus_joined_forms() -> tuple[tuple[str, str], ...]:
    """OCR/bill joined spellings → spaced forms (from JSON via kerala_corpus_maps)."""
    from app.services.kerala_corpus_maps import corpus_joined_forms_tuple

    return corpus_joined_forms_tuple()


@lru_cache(maxsize=1)
def corpus_roman_token_set() -> frozenset[str]:
    """Single-token romanized Malayalam retail vocabulary for detection."""
    tokens: set[str] = set()
    for row in _load_corpus_raw():
        if row.get("language_code") != "ml-roman":
            continue
        term = (row.get("original_term") or "").strip().lower()
        for part in re.split(r"[\s/]+", term):
            if len(part) >= 3 and part.isalpha():
                tokens.add(part)
    return frozenset(tokens - {t.lower() for t in _KERALA_ROMAN_STOP})


def is_romanized_malayalam_retail(text: str) -> bool:
    """True when query is likely romanized Malayalam retail (no script)."""
    if not text or _MALAYALAM_RE.search(text):
        return False
    parts = re.findall(r"[A-Za-z]+", text.lower())
    if not parts:
        return False
    vocab = corpus_roman_token_set()
    hits = sum(1 for p in parts if p in vocab)
    if hits == 0:
        return False
    # Two+ hits, or one hit on a long distinctive token, or majority of tokens
    if hits >= 2:
        return True
    if len(parts) == 1 and len(parts[0]) >= 5 and parts[0] in vocab:
        return True
    return hits / len(parts) >= 0.34


def corpus_stats() -> dict[str, int | bool]:
    from app.services.kerala_corpus_maps import corpus_maps_stats

    raw = _load_corpus_raw()
    derived = corpus_maps_stats()
    return {
        "corpus_path_exists": _CORPUS.exists(),
        "total_rows": len(raw),
        "ml_rows": sum(1 for r in raw if r.get("language_code") == "ml"),
        "ml_roman_rows": sum(1 for r in raw if r.get("language_code") == "ml-roman"),
        "ambiguous_standalone_tokens": derived.get("ambiguous_standalone", 0),
        "transliteration_hints": derived.get("transliterations", 0),
        "joined_form_hints": derived.get("joined_forms", 0),
        "derived_alias_keys": derived.get("derived_alias_keys", 0),
    }
