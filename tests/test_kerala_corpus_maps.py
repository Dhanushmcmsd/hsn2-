"""Tests for corpus-derived Kerala maps (single source of truth)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.kerala_aliases import KERALA_ALIAS_MAP
from app.services.kerala_corpus_maps import (
    corpus_ambiguous_standalone_tokens,
    corpus_derived_alias_map,
    corpus_joined_forms_tuple,
    corpus_maps_stats,
    corpus_transliterations_map,
    is_ambiguous_standalone_query,
    malayalam_transliterations,
)
from app.services.kerala_search import KERALA_FOOD_MAP, strip_kerala_brand_prefix
from app.services.retail_preprocess import (
    preprocess_retail_query,
    retail_alias_query,
    retail_kerala_query,
)

_CORPUS = Path(__file__).resolve().parents[1] / "data" / "kerala_retail_aliases.json"


def test_corpus_maps_stats_stable():
    stats = corpus_maps_stats()
    assert stats["transliterations"] >= 100
    assert stats["joined_forms"] >= 15
    assert stats["ambiguous_standalone"] >= 5


def test_transliterations_exclude_ambiguous_standalone():
    ambiguous = corpus_ambiguous_standalone_tokens()
    translit = corpus_transliterations_map()
    for tok in ambiguous:
        assert tok.lower() not in translit


def test_malayalam_transliterations_matches_corpus_map():
    assert malayalam_transliterations() == corpus_transliterations_map()


def test_joined_forms_include_manjalpodi():
    joined = {a: b for a, b in corpus_joined_forms_tuple()}
    assert "manjalpodi" in joined


def test_derived_alias_map_subset_of_merged_alias_map():
    derived = corpus_derived_alias_map()
    for key in list(derived.keys())[:20]:
        assert key in KERALA_ALIAS_MAP


def test_ambiguous_standalone_blocked_for_exact_query():
    assert is_ambiguous_standalone_query("PULI")
    assert is_ambiguous_standalone_query("THUVARA")
    assert not is_ambiguous_standalone_query("THUVARA PARIPPU")


class TestPhraseVsStandalone:
    @pytest.mark.parametrize(
        "query,needle",
        [
            ("thuvara parippu 1kg", "TOOR"),
            ("nadan ari 5kg", "RICE"),
            ("puli inji 200g", "PICKLE"),
            ("chemmeen achar", "PRAWN"),
        ],
    )
    def test_phrase_expansion(self, query: str, needle: str):
        prep = preprocess_retail_query(query, for_classify=True)
        assert needle in prep.malayalam_expanded

    def test_standalone_nadan_stays_cautious(self):
        prep = preprocess_retail_query("nadan", for_classify=True)
        assert prep.malayalam_expanded.strip() == "NADAN"
        assert "TRADITIONAL" not in prep.malayalam_expanded

    def test_standalone_thuvara_stays_cautious(self):
        prep = preprocess_retail_query("thuvara", for_classify=True)
        assert prep.malayalam_expanded.strip() == "THUVARA"

    def test_standalone_puli_stays_cautious(self):
        prep = preprocess_retail_query("puli", for_classify=True)
        assert prep.malayalam_expanded.strip() == "PULI"

    def test_kodampuli_expands(self):
        prep = preprocess_retail_query("kodampuli 100g", for_classify=True)
        assert "GAMBOGE" in prep.malayalam_expanded or "KODAMPULI" in prep.malayalam_expanded


class TestBrandProduct:
    @pytest.mark.parametrize(
        "query,key",
        [
            ("EASTERN MANJAL PODI 100G", "EASTERN MANJAL PODI"),
            ("NIRAPARA PUTTU PODI", "NIRAPARA PUTTU PODI"),
            ("DOUBLE HORSE APPAM PODI", "DOUBLE HORSE APPAM PODI"),
        ],
    )
    def test_brand_product_alias_keys(self, query: str, key: str):
        assert key in KERALA_ALIAS_MAP
        assert KERALA_ALIAS_MAP[key].get("hsn_code")

    def test_strip_brand_prefix(self):
        assert strip_kerala_brand_prefix("EASTERN MANJAL PODI") == "MANJAL PODI"
        assert strip_kerala_brand_prefix("DOUBLE HORSE APPAM PODI") == "APPAM PODI"


class TestRouteConsistency:
    def test_alias_and_kerala_query_same_for_romanized(self):
        raw = "manjal podi 50g"
        prep = preprocess_retail_query(raw, for_classify=True)
        assert retail_alias_query(prep, fallback=raw) == retail_kerala_query(prep, fallback=raw)

    def test_classify_predict_same_expansion(self):
        raw = "velichenna 1l"
        c = preprocess_retail_query(raw, for_classify=True)
        p = preprocess_retail_query(raw, for_classify=False)
        assert retail_alias_query(c) == retail_alias_query(p)


def test_corpus_row_count_matches_json():
    raw = json.loads(_CORPUS.read_text(encoding="utf-8"))
    stats = corpus_maps_stats()
    assert len(raw) >= 280
    assert stats["derived_alias_keys"] <= len(raw)
