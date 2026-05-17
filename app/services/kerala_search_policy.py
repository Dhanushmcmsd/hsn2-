"""Explicit Kerala/Malayalam search compliance policies (GST/HSN classifier).

This module centralizes intentional design choices that must NOT be weakened for
recall. Wrong confident matches are worse than low-confidence review cases.

See docs/KERALA_SEARCH_POLICY.md for contributor guidance.
"""
from __future__ import annotations

import re
from typing import Any

MALAYALAM_SCRIPT_RE = re.compile(r"[\u0D00-\u0D7F]")

# Invoice abbreviations that may hint when standalone but must not drive strong exact HSN.
# Corpus ambiguous tokens are merged in at import time via corpus_ambiguous_standalone_tokens().
_HINT_ONLY_ABBREV_KEYS: frozenset[str] = frozenset({"nadan"})


def is_canonical_malayalam_script_input(text: str) -> bool:
    """True when query contains Malayalam script (U+0D00–U+0D7F).

    Policy: script input is canonical. We do not guess script→roman in preprocess;
    English/canonical resolution uses seeded language_aliases and exact alias layers.
    """
    return bool(text and MALAYALAM_SCRIPT_RE.search(text))


def hint_only_standalone_tokens() -> frozenset[str]:
    """Lowercase roman tokens that may hint but must not be authoritative alone."""
    from app.services.kerala_corpus_maps import corpus_ambiguous_standalone_tokens

    extra = {t.lower() for t in _HINT_ONLY_ABBREV_KEYS}
    return frozenset(t.lower() for t in corpus_ambiguous_standalone_tokens()) | extra


def is_hint_only_standalone_token(token: str) -> bool:
    """True for ambiguous standalone retail tokens (nadan, puli, thuvara, …)."""
    return (token or "").strip().lower() in hint_only_standalone_tokens()


def _authoritative_kerala_alias_keys() -> frozenset[str]:
    """Curated + corpus alias keys that must not be replaced by English translit in preprocess."""
    from app.services.kerala_aliases import KERALA_ALIAS_MAP

    return frozenset(KERALA_ALIAS_MAP.keys())


def should_skip_standalone_translit_expansion(token: str, *, multi_word: bool) -> bool:
    """Block corpus roman transliteration for ambiguous or authoritative alias tokens."""
    t = (token or "").strip().lower()
    if t.upper() in _authoritative_kerala_alias_keys():
        return True
    if multi_word:
        return is_hint_only_standalone_token(t)
    return is_hint_only_standalone_token(t)


def should_skip_hint_only_abbrev_expansion(raw_abbrev_key: str, *, multi_word: bool) -> bool:
    """Block KERALA_ABBREVIATIONS replacement for hint-only or authoritative alias tokens."""
    if multi_word:
        return False
    key = (raw_abbrev_key or "").strip().upper()
    if is_hint_only_standalone_token(raw_abbrev_key):
        return True
    return key in _authoritative_kerala_alias_keys()


def should_block_standalone_exact_alias(query_upper: str) -> bool:
    """Block in-memory exact KERALA_ALIAS_MAP hits for ambiguous standalone queries."""
    from app.services.kerala_corpus_maps import is_ambiguous_standalone_query

    return is_ambiguous_standalone_query(query_upper)


def merge_alias_maps(
    curated: dict[str, dict[str, Any]],
    derived: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Curated KERALA_ALIAS_MAP entries override corpus-derived keys on conflict."""
    merged = dict(derived)
    merged.update(curated)
    return merged


def curated_overrides_corpus(
    curated: dict[str, dict[str, Any]],
    derived: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Report keys where curated and corpus-derived maps disagree (for diagnostics)."""
    conflicts: list[dict[str, Any]] = []
    for key in sorted(curated):
        if key not in derived:
            continue
        cur_hsn = (curated[key].get("hsn_code") or "").strip()
        der_hsn = (derived[key].get("hsn_code") or "").strip()
        if cur_hsn != der_hsn:
            conflicts.append(
                {
                    "key": key,
                    "curated_hsn": cur_hsn or None,
                    "corpus_hsn": der_hsn or None,
                    "policy": "curated_wins",
                }
            )
    return conflicts


def _row_priority(row: dict[str, Any]) -> int:
    return int(row.get("priority", 100))


def _row_is_ambiguous(row: dict[str, Any]) -> bool:
    if _row_priority(row) < 50:
        return True
    notes = (row.get("notes") or "").lower()
    return "ambiguous standalone" in notes


def analyze_duplicate_corpus_terms(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Group duplicate single-token roman/ml-roman rows; flag conservative ambiguity."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        term = (row.get("original_term") or "").strip().lower()
        if not term or " " in term or MALAYALAM_SCRIPT_RE.search(term):
            continue
        lang = row.get("language_code")
        if lang not in ("ml-roman", "ml"):
            continue
        groups.setdefault(term, []).append(row)

    strictly_ambiguous: list[str] = []
    mixed_priority: list[dict[str, Any]] = []
    for term, entries in sorted(groups.items()):
        priorities = [_row_priority(e) for e in entries]
        any_amb = any(_row_is_ambiguous(e) for e in entries)
        min_pri = min(priorities)
        if any_amb or min_pri < 50:
            strictly_ambiguous.append(term)
        if len(entries) < 2:
            continue
        if len(set(priorities)) > 1 or (any_amb and any(not _row_is_ambiguous(e) for e in entries)):
            mixed_priority.append(
                {
                    "term": term,
                    "row_count": len(entries),
                    "priorities": priorities,
                    "any_ambiguous_row": any_amb,
                    "min_priority": min_pri,
                    "policy": "conservative_block_standalone",
                }
            )

    return {
        "duplicate_token_groups": len([t for t, e in groups.items() if len(e) >= 2]),
        "strictly_ambiguous_terms": strictly_ambiguous,
        "mixed_priority_duplicates": mixed_priority,
    }


def is_kerala_corpus_seed_required(meta: dict[str, Any]) -> bool:
    """True when benchmark metadata indicates Neon seed is missing or critically low."""
    if meta.get("dialect") != "postgresql":
        return False
    expected = int(meta.get("expected_kerala_corpus_rows") or 0)
    if expected <= 0:
        return True
    return not bool(meta.get("kerala_corpus_seeded"))


def seed_status_summary(meta: dict[str, Any]) -> str:
    """Human-readable seed state for benchmarks and diagnostics."""
    dialect = meta.get("dialect", "unknown")
    expected = meta.get("expected_kerala_corpus_rows")
    db_count = meta.get("kerala_corpus_count")
    seeded = meta.get("kerala_corpus_seeded")
    if dialect != "postgresql":
        return f"dialect={dialect} (Kerala DB seed not applicable)"
    if seeded:
        return f"seeded OK: DB={db_count} JSON≈{expected}"
    return f"NOT SEEDED: DB={db_count} JSON≈{expected} — run scripts/seed_kerala_language_aliases.py"
