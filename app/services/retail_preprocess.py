"""Single source of truth for Kerala/Malayalam retail query preprocessing.

Used by classify(), predict(), multi_search, and client Excel smoke tests.
Vocabulary for transliteration/joined forms comes from data/kerala_retail_aliases.json
via kerala_corpus_maps; invoice abbreviations remain in kerala_aliases (logic-driven).

Policy (do not weaken for recall — see docs/KERALA_SEARCH_POLICY.md):
  - Malayalam script (U+0D00–U+0D7F) is canonical: no roman expansion in preprocess.
  - Roman/ml-roman expansion uses corpus + invoice hints; ambiguous standalone tokens
    skip strong translit/abbrev unless the query is multi-word (phrase-first).
  - Authoritative English/HSN for script queries comes from language_aliases (DB seed).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.kerala_aliases import KERALA_ABBREVIATIONS
from app.services.kerala_corpus_hints import corpus_joined_forms
from app.services.kerala_corpus_maps import (
    corpus_transliterations_map,
    malayalam_transliterations,
)
from app.services.kerala_search_policy import (
    is_canonical_malayalam_script_input,
    is_hint_only_standalone_token,
    should_skip_hint_only_abbrev_expansion,
    should_skip_standalone_translit_expansion,
)
from app.services.matcher import expand_fmcg_abbreviations, strip_sizes, tokenize
from app.services.normalizer import fix_retail_typos, normalize_product_name

MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")  # prefer is_canonical_malayalam_script_input()

# Backward-compatible export (corpus-derived at load time).
MALAYALAM_TRANSLITERATIONS: dict[str, str] = malayalam_transliterations()


def _all_joined_forms() -> tuple[tuple[str, str], ...]:
    return corpus_joined_forms()


def _split_joined_kerala_compounds(text_value: str) -> str:
    """Insert spaces into common joined Kerala retail spellings before expansion."""
    lower = text_value.lower()
    for joined, spaced in _all_joined_forms():
        if joined in lower:
            pattern = re.compile(re.escape(joined), re.IGNORECASE)
            lower = pattern.sub(spaced, lower)
    return lower


def _normalize_ws(text_value: str) -> str:
    return re.sub(r"\s+", " ", text_value.strip().upper())


def _token_count_alpha(text_value: str) -> int:
    return len(re.findall(r"[A-Za-z]+", text_value.lower()))


def apply_kerala_expansion(query: str) -> str:
    """Kerala invoice + romanized Malayalam expansion (in-memory, no DB).

    Does not transliterate Malayalam script — callers must use preprocess_retail_query.
    """
    query = _split_joined_kerala_compounds(query)
    normalized = _normalize_ws(query)
    expanded = normalized

    lower_expanded = expanded.lower()
    translit = corpus_transliterations_map()
    multi_word = _token_count_alpha(lower_expanded) > 1
    hint_only_single = not multi_word and is_hint_only_standalone_token(lower_expanded.strip())

    # Phrase-level corpus expansions before invoice abbreviations (e.g. nadan ari before nadan).
    for mal_word, english_equiv in sorted(translit.items(), key=lambda x: len(x[0]), reverse=True):
        if " " not in mal_word:
            continue
        pattern = re.compile(rf"\b{re.escape(mal_word.lower())}\b")
        if pattern.search(lower_expanded):
            lower_expanded = pattern.sub(english_equiv.lower(), lower_expanded)

    expanded = lower_expanded.upper()
    for raw, replacement in sorted(
        KERALA_ABBREVIATIONS.items(), key=lambda x: len(x[0]), reverse=True
    ):
        if should_skip_hint_only_abbrev_expansion(raw, multi_word=multi_word):
            continue
        pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(raw.upper())}(?![A-Z0-9])")
        expanded = pattern.sub(replacement.upper(), expanded)

    # FMCG dict includes KERALA_ABBREVIATIONS — skip for hint-only standalone singles.
    if not hint_only_single:
        expanded = expand_fmcg_abbreviations(expanded).upper()
    lower_expanded = expanded.lower()
    multi_word = _token_count_alpha(lower_expanded) > 1

    for mal_word, english_equiv in sorted(translit.items(), key=lambda x: len(x[0]), reverse=True):
        if " " in mal_word:
            continue
        if should_skip_standalone_translit_expansion(mal_word, multi_word=multi_word):
            continue
        pattern = re.compile(rf"\b{re.escape(mal_word.lower())}\b")
        if pattern.search(lower_expanded):
            lower_expanded = pattern.sub(english_equiv.lower(), lower_expanded)

    expanded = lower_expanded.upper()
    return _normalize_ws(strip_sizes(expanded))


def expand_kerala_query(query: str) -> str:
    """Backward-compatible alias used across the codebase."""
    return apply_kerala_expansion(query)


@dataclass
class RetailPreprocessResult:
    original: str
    normalized: str
    typo_fixed: str
    malayalam_expanded: str
    canonical: str
    retail_tokens: list[str] = field(default_factory=list)
    kerala_applied: bool = False
    detected_language: str = "en"
    for_classify: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "normalized": self.normalized,
            "typo_fixed": self.typo_fixed,
            "malayalam_expanded": self.malayalam_expanded,
            "canonical": self.canonical,
            "retail_tokens": self.retail_tokens,
            "kerala_applied": self.kerala_applied,
            "detected_language": self.detected_language,
            "for_classify": self.for_classify,
        }


def retail_alias_query(prep: RetailPreprocessResult, *, fallback: str = "") -> str:
    """Query string for language_aliases / multi_search L0 (Kerala-expanded when available)."""
    return (prep.malayalam_expanded or prep.canonical or prep.normalized or fallback).strip()


def retail_kerala_query(prep: RetailPreprocessResult, *, fallback: str = "") -> str:
    """Query string for kerala_fallback_search — same expansion priority as alias path."""
    return retail_alias_query(prep, fallback=fallback or prep.original)


def preprocess_retail_query(query: str, *, for_classify: bool = False) -> RetailPreprocessResult:
    """Normalize, fix OCR typos, and apply Kerala/Malayalam expansion."""
    original = (query or "").strip()
    if not original:
        return RetailPreprocessResult(
            original="",
            normalized="",
            typo_fixed="",
            malayalam_expanded="",
            canonical="",
            for_classify=for_classify,
        )

    typo_fixed = fix_retail_typos(_split_joined_kerala_compounds(original))
    from app.services.aliases import detect_language

    detected = detect_language(original, typo_fixed=typo_fixed)
    normalized_name = normalize_product_name(typo_fixed)
    normalized = _normalize_ws(normalized_name if normalized_name else typo_fixed)

    before_kerala = normalized
    # Malayalam script is canonical — no hacky script→roman loop; DB language_aliases resolve.
    if is_canonical_malayalam_script_input(typo_fixed):
        malayalam_expanded = _normalize_ws(normalize_product_name(typo_fixed) or typo_fixed)
        kerala_applied = False
    else:
        malayalam_expanded = apply_kerala_expansion(typo_fixed)
        kerala_applied = malayalam_expanded != before_kerala

    canonical = malayalam_expanded
    retail_tokens = tokenize(canonical)

    return RetailPreprocessResult(
        original=original,
        normalized=normalized,
        typo_fixed=_normalize_ws(typo_fixed) if typo_fixed else normalized,
        malayalam_expanded=malayalam_expanded,
        canonical=canonical,
        retail_tokens=retail_tokens,
        kerala_applied=kerala_applied,
        detected_language=detected,
        for_classify=for_classify,
    )
