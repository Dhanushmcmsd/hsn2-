"""Validation and normalization for Kerala retail language_aliases seed corpus."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.services.aliases import normalize_term

MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")
DEFAULT_SOURCE = "KERALA_RETAIL_CORPUS"
DEFAULT_WEIGHT = 100.0
REQUIRED_FIELDS = ("language_code", "original_term")


class KeralaSeedValidationError(ValueError):
    """Raised when a corpus row fails validation."""


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_seed_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Map JSON corpus fields to language_aliases columns."""
    if not isinstance(raw, dict):
        raise KeralaSeedValidationError(f"Entry must be an object, got {type(raw).__name__}")

    for field in REQUIRED_FIELDS:
        if field not in raw or not str(raw[field]).strip():
            raise KeralaSeedValidationError(f"Missing required field: {field}")

    language = str(raw["language_code"]).strip().lower()
    if language not in ("ml", "ml-roman", "en", "hi"):
        raise KeralaSeedValidationError(f"Unsupported language_code: {language!r}")

    original = _collapse_ws(str(raw["original_term"]))
    if not original:
        raise KeralaSeedValidationError("original_term is empty after trim")

    normalized_raw = raw.get("normalized_term") or original
    term_normalized = _collapse_ws(str(normalized_raw))
    if MALAYALAM_RE.search(term_normalized):
        term_normalized = unicodedata.normalize("NFC", term_normalized)
    else:
        term_normalized = normalize_term(term_normalized) or term_normalized.upper()

    english = raw.get("english_term") or raw.get("canonical_query") or ""
    english_term = _collapse_ws(str(english)) if english else None

    hsn_raw = raw.get("hsn_code")
    hsn_code = None
    if hsn_raw is not None and str(hsn_raw).strip():
        digits = re.sub(r"[^0-9]", "", str(hsn_raw))
        if len(digits) not in (4, 6, 8):
            raise KeralaSeedValidationError(f"Invalid hsn_code: {hsn_raw!r}")
        hsn_code = digits

    weight = float(raw.get("priority", raw.get("weight", DEFAULT_WEIGHT)))
    if weight <= 0:
        raise KeralaSeedValidationError(f"priority/weight must be positive, got {weight}")

    is_active = bool(raw.get("is_active", True))
    source = str(raw.get("source") or DEFAULT_SOURCE).strip() or DEFAULT_SOURCE

    return {
        "term": original,
        "term_normalized": term_normalized,
        "language": language,
        "hsn_code": hsn_code,
        "english_term": english_term,
        "weight": weight,
        "source": source,
        "is_active": is_active,
        "notes": raw.get("notes"),
    }


def load_corpus(path: Path) -> list[dict[str, Any]]:
    """Load JSON array or directory of *.json files."""
    if path.is_dir():
        entries: list[dict[str, Any]] = []
        for fp in sorted(path.glob("*.json")):
            entries.extend(load_corpus(fp))
        return entries

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "entries" in data:
        data = data["entries"]
    if not isinstance(data, list):
        raise KeralaSeedValidationError(f"{path}: root must be a JSON array")
    return data


def validate_and_normalize_corpus(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return normalized rows and validation error messages."""
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, str, str | None]] = set()

    for idx, raw in enumerate(entries):
        try:
            row = normalize_seed_entry(raw)
        except KeralaSeedValidationError as exc:
            errors.append(f"row {idx}: {exc}")
            continue

        key = (row["term_normalized"], row["language"], row["hsn_code"])
        if key in seen:
            errors.append(f"row {idx}: duplicate ({key[0]!r}, {key[1]!r}, {key[2]!r})")
            continue
        seen.add(key)
        normalized.append(row)

    return normalized, errors


def dedupe_for_upsert(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Last row wins for identical (term_normalized, language, hsn_code)."""
    by_key: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for row in rows:
        key = (row["term_normalized"], row["language"], row["hsn_code"])
        by_key[key] = row
    return list(by_key.values())
