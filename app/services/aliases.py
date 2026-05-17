"""Hindi / Malayalam (and English) alias + synonym expansion for the search layer.

Loads from the ``language_aliases`` and ``search_synonyms`` tables (gov-aligned
content seeded via Alembic revision a4b7c9e21f33), keeps an in-memory snapshot,
and refreshes lazily so per-request expansion stays in-process and microsecond-fast.

When an in-memory exact lookup misses (most Romanized typing — *paani*, *pappad*,
*panneer*, *biriyaani*, *sambhar* — has many spellings), we transparently fall
through to a Postgres-side fuzzy resolver that combines:

    - trigram similarity on ``term_normalized`` (catches typos, dropped letters)
    - metaphone phonetic equivalence (paani \u2248 pani \u2248 panee, paneer \u2248 panneer)
    - dmetaphone fallback (catches more aggressive consonant collisions)

Each resolved token is cached in a small LRU so repeated queries stay sub-ms.

This module is independent of the existing matcher: failures fall back to a
no-op (returns the original query) so the rest of the multi-layer pipeline
keeps working even if the DB is unreachable.
"""
from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

REFRESH_INTERVAL_SECONDS = 600
MAX_EXPANSIONS_PER_QUERY = 12
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")

# Token-level fuzzy lookup tuning (defaults for predict path; classify overrides per call)
from app.services.search_thresholds import (
    PREDICT_ALIAS_FUZZY_MIN_TRGM as FUZZY_MIN_TRGM_SIM,
    PREDICT_ALIAS_PHONETIC_MIN_TRGM as FUZZY_PHONETIC_MIN_TRGM,
    alias_fuzzy_min_trgm,
    alias_phonetic_min_trgm,
)
FUZZY_MIN_TOKEN_LEN = 3            # don't fuzzy-match 1-2 char tokens (too noisy)
FUZZY_LRU_CAPACITY = 1024          # ~50KB at most
FUZZY_LOOKUP_TIMEOUT_S = 0.35      # never block longer than this on the resolver

# Tokens that we never want to fuzzy-resolve (English stopwords / size words /
# noise). Kept tiny — heavier filtering happens in the matcher.
_FUZZY_STOPWORDS = {
    "the", "and", "for", "with", "from", "size", "pack", "kg", "gm", "ml",
    "ltr", "pcs", "no", "nos", "buy", "get", "new",
}


@dataclass
class AliasIndex:
    by_normalized: dict[str, list[dict]] = field(default_factory=dict)
    by_raw_term: dict[str, list[dict]] = field(default_factory=dict)
    synonyms: dict[str, list[dict]] = field(default_factory=dict)
    loaded_at: float = 0.0
    languages: set[str] = field(default_factory=set)

    @property
    def is_empty(self) -> bool:
        return not self.by_normalized and not self.by_raw_term and not self.synonyms


_INDEX = AliasIndex()
_LOCK = asyncio.Lock()
_FUZZY_LRU: OrderedDict[str, list[dict]] = OrderedDict()
_FUZZY_LRU_LOCK = asyncio.Lock()
_LOCAL_KERALA_MERGED = False
_KERALA_JSON = Path(__file__).resolve().parents[2] / "data" / "kerala_retail_aliases.json"


def _fuzzy_cache_get(key: str) -> list[dict] | None:
    if key in _FUZZY_LRU:
        value = _FUZZY_LRU.pop(key)
        _FUZZY_LRU[key] = value  # mark as recently used
        return value
    return None


def _fuzzy_cache_put(key: str, value: list[dict]) -> None:
    _FUZZY_LRU[key] = value
    while len(_FUZZY_LRU) > FUZZY_LRU_CAPACITY:
        _FUZZY_LRU.popitem(last=False)


_FUZZY_SQL = text(
    """
    WITH q AS (
        SELECT
            UPPER(:token)::text AS up,
            metaphone(regexp_replace(:token, '[^A-Za-z]', '', 'g'), 6)  AS mp,
            dmetaphone(regexp_replace(:token, '[^A-Za-z]', '', 'g'))    AS dmp
    )
    SELECT
        a.term,
        a.term_normalized,
        a.language,
        a.hsn_code,
        a.english_term,
        a.weight,
        similarity(a.term_normalized::text, q.up) AS sim,
        (a.term_metaphone  IS NOT NULL AND a.term_metaphone  = q.mp)  AS phon,
        (a.term_dmetaphone IS NOT NULL AND a.term_dmetaphone = q.dmp) AS dphon
    FROM language_aliases a, q
    WHERE a.is_active = TRUE
      AND (
            a.term_normalized::text %% q.up
         OR a.term_metaphone  = q.mp
         OR a.term_dmetaphone = q.dmp
      )
    ORDER BY sim DESC, a.weight DESC
    LIMIT 8
    """
)


def detect_language(text_value: str, *, typo_fixed: str | None = None) -> str:
    if not text_value:
        return "en"
    if DEVANAGARI_RE.search(text_value):
        return "hi"
    if MALAYALAM_RE.search(text_value):
        return "ml"
    try:
        from app.services.kerala_corpus_hints import is_romanized_malayalam_retail

        probe = " ".join(filter(None, [text_value, typo_fixed]))
        if is_romanized_malayalam_retail(probe):
            return "ml-roman"
    except Exception:
        pass
    return "en"


def normalize_term(value: str) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    cleaned = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^\w\s]", " ", cleaned, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip().upper()


async def refresh(db: AsyncSession, *, force: bool = False) -> AliasIndex:
    """Reload the alias + synonym caches from Neon."""
    now = time.monotonic()
    if not force and _INDEX.loaded_at and (now - _INDEX.loaded_at) < REFRESH_INTERVAL_SECONDS:
        return _INDEX
    async with _LOCK:
        if not force and _INDEX.loaded_at and (now - _INDEX.loaded_at) < REFRESH_INTERVAL_SECONDS:
            return _INDEX
        try:
            alias_rows = (
                await db.execute(
                    text(
                        "SELECT term, term_normalized, language, hsn_code, english_term, weight "
                        "FROM language_aliases WHERE is_active = TRUE"
                    )
                )
            ).mappings().all()
            syn_rows = (
                await db.execute(
                    text(
                        "SELECT term, synonym, weight, language "
                        "FROM search_synonyms WHERE is_active = TRUE"
                    )
                )
            ).mappings().all()
        except Exception as exc:
            log.warning("aliases.load_failed", error=str(exc))
            _INDEX.loaded_at = now
            return _INDEX

        by_normalized: dict[str, list[dict]] = {}
        by_raw_term: dict[str, list[dict]] = {}
        languages: set[str] = set()
        for row in alias_rows:
            payload = {
                "term": row["term"],
                "term_normalized": row["term_normalized"],
                "language": row["language"],
                "hsn_code": row["hsn_code"],
                "english_term": row["english_term"],
                "weight": float(row["weight"] or 1.0),
            }
            languages.add(row["language"])
            by_normalized.setdefault(row["term_normalized"], []).append(payload)
            by_raw_term.setdefault((row["term"] or "").strip(), []).append(payload)

        synonyms: dict[str, list[dict]] = {}
        for row in syn_rows:
            term = (row["term"] or "").strip().lower()
            if not term:
                continue
            synonyms.setdefault(term, []).append(
                {
                    "synonym": row["synonym"],
                    "weight": float(row["weight"] or 1.0),
                    "language": row["language"] or "en",
                }
            )

        _INDEX.by_normalized = by_normalized
        _INDEX.by_raw_term = by_raw_term
        _INDEX.synonyms = synonyms
        _INDEX.languages = languages
        _INDEX.loaded_at = now
        log.info(
            "aliases.loaded",
            aliases=len(alias_rows),
            synonyms=len(syn_rows),
            languages=sorted(languages),
        )
    return _INDEX


def _lookup_aliases(token: str) -> list[dict]:
    if not token:
        return []
    matches: list[dict] = []
    raw_match = _INDEX.by_raw_term.get(token)
    if raw_match:
        matches.extend(raw_match)
    norm = normalize_term(token)
    if norm and norm != token:
        matches.extend(_INDEX.by_normalized.get(norm, []))
    return matches


def _lookup_synonyms(token: str) -> list[dict]:
    if not token:
        return []
    return _INDEX.synonyms.get(token.lower(), [])


@dataclass
class ExpansionResult:
    original: str
    detected_language: str
    english_query: str
    expansions: list[str] = field(default_factory=list)
    direct_hsn_hints: list[dict] = field(default_factory=list)

    def all_text_variants(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        candidates = [self.english_query, self.original, *self.expansions]
        for c in candidates:
            key = (c or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(c.strip())
        return out


def expand(query: str) -> ExpansionResult:
    """Pure in-memory expansion using the loaded index. Fast (~50µs per call)."""
    original = (query or "").strip()
    if not original:
        return ExpansionResult(original="", detected_language="en", english_query="")

    detected = detect_language(original)
    tokens = re.findall(r"\S+", original)
    expansions: list[str] = []
    english_tokens: list[str] = []
    direct_hits: list[dict] = []

    for token in tokens:
        alias_matches = _lookup_aliases(token)
        syn_matches = _lookup_synonyms(token)

        replaced = False
        if alias_matches:
            top = max(alias_matches, key=lambda r: r["weight"])
            if top.get("english_term"):
                english_tokens.append(top["english_term"])
                replaced = True
            for match in alias_matches[:4]:
                if match.get("english_term"):
                    expansions.append(match["english_term"])
                if match.get("hsn_code"):
                    direct_hits.append(
                        {
                            "hsn_code": match["hsn_code"],
                            "source_term": match["term"],
                            "language": match["language"],
                            "weight": match["weight"],
                        }
                    )
        if not replaced:
            english_tokens.append(token)

        for syn in syn_matches[:3]:
            expansions.append(syn["synonym"])

    english_query = " ".join(english_tokens).strip() or original
    expansions = [e for e in dict.fromkeys(expansions) if e and e.lower() != english_query.lower()][
        :MAX_EXPANSIONS_PER_QUERY
    ]
    return ExpansionResult(
        original=original,
        detected_language=detected,
        english_query=english_query,
        expansions=expansions,
        direct_hsn_hints=direct_hits[:8],
    )


def _ensure_loaded() -> bool:
    return not _INDEX.is_empty


def _merge_local_kerala_fallback() -> None:
    """Load Kerala JSON corpus into memory when Postgres language_aliases is unavailable."""
    global _LOCAL_KERALA_MERGED
    if _LOCAL_KERALA_MERGED or not _INDEX.is_empty:
        return
    if not _KERALA_JSON.exists():
        _LOCAL_KERALA_MERGED = True
        return
    try:
        from app.services.kerala_seed import dedupe_for_upsert, load_corpus, validate_and_normalize_corpus

        raw = load_corpus(_KERALA_JSON)
        rows, errors = validate_and_normalize_corpus(raw)
        if errors:
            log.warning("aliases.local_kerala_validation_errors", count=len(errors))
        for row in dedupe_for_upsert(rows):
            payload = {
                "term": row["term"],
                "term_normalized": row["term_normalized"],
                "language": row["language"],
                "hsn_code": row["hsn_code"],
                "english_term": row["english_term"],
                "weight": float(row["weight"]),
            }
            _INDEX.by_normalized.setdefault(row["term_normalized"], []).append(payload)
            _INDEX.by_raw_term.setdefault((row["term"] or "").strip(), []).append(payload)
            _INDEX.languages.add(row["language"])
        _INDEX.loaded_at = time.monotonic()
        _LOCAL_KERALA_MERGED = True
        log.info("aliases.local_kerala_loaded", entries=len(rows))
    except Exception as exc:
        log.warning("aliases.local_kerala_failed", error=str(exc)[:120])
        _LOCAL_KERALA_MERGED = True


def local_kerala_fallback_stats() -> dict[str, int | bool]:
    _merge_local_kerala_fallback()
    ml = sum(1 for k, v in _INDEX.by_normalized.items() if v and v[0].get("language", "").startswith("ml"))
    return {
        "loaded": _LOCAL_KERALA_MERGED,
        "malayalam_keys": ml,
        "total_normalized_keys": len(_INDEX.by_normalized),
    }


async def _fuzzy_resolve_token(
    db: AsyncSession,
    token: str,
    *,
    for_classify: bool = False,
) -> list[dict]:
    """Resolve a single Romanized token via trigram + phonetic match.

    Returns a list of alias-row dicts (term, language, hsn_code, english_term,
    weight, sim, phon). Empty list when nothing crosses the thresholds. Cached
    in an in-process LRU keyed by the lowercased token.
    """
    if not token:
        return []
    key = token.lower()
    if key in _FUZZY_STOPWORDS or len(key) < FUZZY_MIN_TOKEN_LEN:
        return []

    cached = _fuzzy_cache_get(key)
    if cached is not None:
        return cached

    async with _FUZZY_LRU_LOCK:
        cached = _fuzzy_cache_get(key)
        if cached is not None:
            return cached

        min_trgm = alias_fuzzy_min_trgm(for_classify=for_classify)
        phon_min = alias_phonetic_min_trgm(for_classify=for_classify)
        try:
            await db.execute(text("SELECT set_limit(:s)"), {"s": float(phon_min)})
            rows = (
                await asyncio.wait_for(
                    db.execute(_FUZZY_SQL, {"token": token}),
                    timeout=FUZZY_LOOKUP_TIMEOUT_S,
                )
            ).mappings().all()
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            log.debug("aliases.fuzzy_failed", error=str(exc)[:120], token=token[:40])
            _fuzzy_cache_put(key, [])
            return []

        out: list[dict] = []
        for r in rows:
            sim = float(r["sim"] or 0.0)
            is_phon = bool(r["phon"]) or bool(r["dphon"])
            # Two acceptance paths:
            #   1) High lexical (trigram) similarity            \u2192 strong typo match
            #   2) Phonetic match + acceptable lexical similarity \u2192 catches paani/pani/panee
            if sim >= min_trgm or (is_phon and sim >= phon_min):
                out.append(
                    {
                        "term": r["term"],
                        "term_normalized": r["term_normalized"],
                        "language": r["language"],
                        "hsn_code": r["hsn_code"],
                        "english_term": r["english_term"],
                        "weight": float(r["weight"] or 1.0) * (sim if sim > 0 else 0.6),
                        "sim": sim,
                        "phonetic": is_phon,
                    }
                )
        _fuzzy_cache_put(key, out)
        return out


async def expand_query(
    db: AsyncSession,
    query: str,
    *,
    for_classify: bool = False,
) -> ExpansionResult:
    """Public entry: refresh cache lazily then expand. Falls through to fuzzy
    + phonetic resolution for any token that the in-memory exact map misses."""
    await refresh(db)
    if not _ensure_loaded():
        _merge_local_kerala_fallback()
    base = (query or "").strip()
    detected = detect_language(base)
    if not base:
        return ExpansionResult(original="", detected_language="en", english_query="")
    if not _ensure_loaded():
        return ExpansionResult(original=base, detected_language=detected, english_query=base)

    # Step 1: in-memory exact expansion (microsecond-fast).
    fast = expand(base)
    matched_tokens: set[str] = set()
    for hint in fast.direct_hsn_hints:
        if hint.get("source_term"):
            matched_tokens.add(hint["source_term"].lower())
    matched_norm: set[str] = set()
    for token in re.findall(r"\S+", base):
        norm = normalize_term(token)
        if norm and norm in _INDEX.by_normalized:
            matched_norm.add(token.lower())

    # Step 2: For each token that the in-memory layer did NOT resolve, try the
    # Postgres-side fuzzy + phonetic resolver. This is what powers paani / pani /
    # panneer / pappad / sambhar / biriyaani.
    unresolved = [
        t
        for t in re.findall(r"\S+", base)
        if t.lower() not in matched_tokens and t.lower() not in matched_norm
    ]
    if not unresolved:
        return fast

    extra_english: list[str] = list(fast.english_query.split()) if fast.english_query else base.split()
    extra_expansions: list[str] = list(fast.expansions)
    extra_hints: list[dict] = list(fast.direct_hsn_hints)

    fuzzy_results = await asyncio.gather(
        *(_fuzzy_resolve_token(db, t, for_classify=for_classify) for t in unresolved),
        return_exceptions=True,
    )

    # Replace each unresolved token with its top fuzzy English term (if any).
    tokens_in_order = re.findall(r"\S+", base)
    rebuilt_english: list[str] = []
    seen_hint_codes: set[str] = {h.get("hsn_code") for h in extra_hints if h.get("hsn_code")}

    fuzzy_by_token: dict[str, list[dict]] = {}
    for token, result in zip(unresolved, fuzzy_results):
        if isinstance(result, Exception):
            continue
        fuzzy_by_token[token.lower()] = result

    for token in tokens_in_order:
        key = token.lower()
        matches = fuzzy_by_token.get(key)
        if matches:
            top = max(matches, key=lambda r: (r["weight"], r["sim"]))
            if top.get("english_term"):
                rebuilt_english.append(top["english_term"])
            else:
                rebuilt_english.append(token)
            for m in matches[:3]:
                if m.get("english_term"):
                    extra_expansions.append(m["english_term"])
                code = m.get("hsn_code")
                if code and code not in seen_hint_codes:
                    seen_hint_codes.add(code)
                    extra_hints.append(
                        {
                            "hsn_code": code,
                            "source_term": m["term"],
                            "language": m["language"],
                            "weight": float(m["weight"]),
                        }
                    )
        else:
            rebuilt_english.append(token)

    new_english = " ".join(rebuilt_english).strip() or fast.english_query or base
    dedup_expansions = [e for e in dict.fromkeys(extra_expansions) if e and e.lower() != new_english.lower()][
        :MAX_EXPANSIONS_PER_QUERY
    ]
    return ExpansionResult(
        original=base,
        detected_language=detected,
        english_query=new_english,
        expansions=dedup_expansions,
        direct_hsn_hints=extra_hints[:8],
    )


def loaded_languages() -> Iterable[str]:
    return tuple(sorted(_INDEX.languages))
