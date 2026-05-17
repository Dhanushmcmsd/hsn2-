"""Tests for Kerala retail language_aliases seed corpus validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.kerala_seed import (
    KeralaSeedValidationError,
    dedupe_for_upsert,
    load_corpus,
    normalize_seed_entry,
    validate_and_normalize_corpus,
)

CORPUS = Path(__file__).resolve().parents[1] / "data" / "kerala_retail_aliases.json"


def test_corpus_file_loads():
    entries = load_corpus(CORPUS)
    assert len(entries) >= 50


def test_validate_corpus_no_errors():
    entries = load_corpus(CORPUS)
    rows, errors = validate_and_normalize_corpus(entries)
    assert not errors
    assert len(rows) == len(entries)


def test_malayalam_script_normalized():
    row = normalize_seed_entry(
        {
            "language_code": "ml",
            "original_term": "ചായപ്പൊടി",
            "english_term": "tea powder",
            "hsn_code": "09024090",
        }
    )
    assert row["language"] == "ml"
    assert row["term_normalized"] == "ചായപ്പൊടി"
    assert row["weight"] == 100.0


def test_malformed_row_rejected():
    with pytest.raises(KeralaSeedValidationError):
        normalize_seed_entry({"language_code": "ml"})


def test_duplicate_key_in_validation():
    entries = [
        {"language_code": "ml-roman", "original_term": "PUTTU", "hsn_code": "11023000"},
        {"language_code": "ml-roman", "original_term": "PUTTU", "hsn_code": "11023000"},
    ]
    rows, errors = validate_and_normalize_corpus(entries)
    assert len(rows) == 1
    assert any("duplicate" in e for e in errors)


def test_dedupe_for_upsert_last_wins():
    rows = dedupe_for_upsert(
        [
            {
                "term": "A",
                "term_normalized": "A",
                "language": "ml-roman",
                "hsn_code": "11023000",
                "english_term": "one",
                "weight": 1.0,
                "source": "KERALA_RETAIL_CORPUS",
                "is_active": True,
            },
            {
                "term": "A",
                "term_normalized": "A",
                "language": "ml-roman",
                "hsn_code": "11023000",
                "english_term": "two",
                "weight": 100.0,
                "source": "KERALA_RETAIL_CORPUS",
                "is_active": True,
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["english_term"] == "two"
