"""Kerala retail romanized / script / OCR regression suite."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.aliases import detect_language
from app.services.kerala_aliases import KERALA_ALIAS_MAP
from app.services.kerala_corpus_hints import is_romanized_malayalam_retail
from app.services.kerala_seed import load_corpus, validate_and_normalize_corpus
from app.services.retail_preprocess import preprocess_retail_query
from app.services.search_thresholds import (
    brand_early_exit_min_score,
    should_skip_brand_early_exit,
)

_CORPUS = Path(__file__).resolve().parents[1] / "data" / "kerala_retail_aliases.json"

_ROMANIZED_EXPANSIONS = [
    ("manjal podi", "TURMERIC"),
    ("mulaku podi", "CHILLI"),
    ("velichenna 1l", "COCONUT"),
    ("kaayam", "ASAFOETIDA"),
    ("puzhukkalari", "PARBOILED"),
    ("thuvara parippu", "TOOR"),
    ("kadala mavu", "BESAN"),
    ("nendran chips", "BANANA"),
    ("idiyappam podi", "IDIYAPPAM"),
    ("gothambu podi", "WHEAT"),
    ("mallipodi", "CORIANDER"),
    ("puli inji", "PICKLE"),
]

_JOINED_FORMS = [
    ("manjalpodi 100g", "TURMERIC"),
    ("chaayapodi", "TEA"),
    ("puttupodi", "PUTTU"),
    ("vellachenna", "COCONUT"),
]

_MALAYALAM_SCRIPT = [
    "\u0d35\u0d46\u0d33\u0d3f\u0d1a\u0d4d\u0d1a\u0d46\u0d23\u0d4d\u0d23",
    "\u0d2e\u0d1e\u0d4d\u0d1e\u0d33\u0d4d\u0d2a\u0d4b\u0d1f\u0d3f",
]


class TestKeralaCorpus:
    def test_corpus_validates(self):
        raw = json.loads(_CORPUS.read_text(encoding="utf-8"))
        rows, errors = validate_and_normalize_corpus(raw)
        assert not errors, errors
        assert len(rows) >= 280
        assert all(r.get("english_term") for r in rows if r["language"] == "ml")

    def test_key_romanized_terms_in_corpus(self):
        terms = {e["original_term"].upper() for e in load_corpus(_CORPUS)}
        for required in (
            "VELICHENNA", "MULAKU PODI", "PUZHUKKALARI", "MANJALPODI", "PUTTUPODI",
        ):
            assert required in terms


class TestRetailPreprocess:
    @pytest.mark.parametrize("query,needle", _ROMANIZED_EXPANSIONS)
    def test_romanized_expansion(self, query: str, needle: str):
        prep = preprocess_retail_query(query, for_classify=True)
        assert needle in prep.malayalam_expanded

    @pytest.mark.parametrize("query,needle", _JOINED_FORMS)
    def test_joined_ocr_forms(self, query: str, needle: str):
        prep = preprocess_retail_query(query, for_classify=False)
        assert needle in prep.malayalam_expanded

    @pytest.mark.parametrize("query", _MALAYALAM_SCRIPT)
    def test_malayalam_script_passthrough(self, query: str):
        prep = preprocess_retail_query(query, for_classify=True)
        assert prep.detected_language == "ml"
        assert prep.normalized == query.strip()
        assert prep.original == query.strip()


class TestKeralaAliasMap:
    @pytest.mark.parametrize(
        "key",
        ["MANJAL PODI", "VELICHENNA", "PUTTU PODI", "PUZHUKKALARI"],
    )
    def test_exact_map_keys(self, key: str):
        assert key in KERALA_ALIAS_MAP
        assert KERALA_ALIAS_MAP[key].get("hsn_code")


class TestBrandEarlyExitGuards:
    def test_classify_short_brand_higher_floor(self):
        assert brand_early_exit_min_score("BRU", for_classify=True) > brand_early_exit_min_score(
            "BRU", for_classify=False,
        )

    def test_commodity_token_blocks_early_exit(self):
        assert brand_early_exit_min_score("MILK", for_classify=True) >= 1.0

    def test_skip_early_exit_for_malayalam_classify(self):
        assert should_skip_brand_early_exit(
            for_classify=True,
            detected_language="ml",
            has_direct_alias_hsn=False,
        )

    def test_predict_does_not_skip_on_malayalam(self):
        assert not should_skip_brand_early_exit(
            for_classify=False,
            detected_language="ml",
            has_direct_alias_hsn=False,
        )


class TestRomanizedMalayalamDetection:
    def test_romanized_retail_detected(self):
        assert is_romanized_malayalam_retail("velichenna 1l")
        assert detect_language("manjal podi 100g") == "ml-roman"

    def test_classify_skips_brand_early_exit_for_ml_roman(self):
        assert should_skip_brand_early_exit(
            for_classify=True,
            detected_language="ml-roman",
            has_direct_alias_hsn=False,
        )


class TestAmbiguousCorpusTokens:
    def test_ambiguous_standalone_low_priority(self):
        raw = json.loads(_CORPUS.read_text(encoding="utf-8"))
        by_term = {
            (e["original_term"].upper(), e.get("language_code")): e
            for e in raw
            if e.get("language_code") == "ml-roman"
        }
        for tok in ("PULI", "THUVARA", "NADAN"):
            row = by_term.get((tok, "ml-roman"))
            assert row is not None
            assert int(row.get("priority", 100)) < 50 or not row.get("hsn_code")
