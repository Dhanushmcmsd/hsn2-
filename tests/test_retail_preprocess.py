"""Tests for unified retail preprocess path."""
from __future__ import annotations

from app.services.kerala_search import expand_kerala_query
from app.services.retail_preprocess import preprocess_retail_query


def test_malayalam_script_passthrough_in_preprocess():
    ml = "\u0d2e\u0d1e\u0d4d\u0d1e\u0d33\u0d4d\u0d2a\u0d4b\u0d1f\u0d3f"
    prep = preprocess_retail_query(ml, for_classify=True)
    assert prep.normalized == ml
    assert prep.detected_language == "ml"


def test_romanized_malayalam_expansion():
    prep = preprocess_retail_query("manjal podi 100g", for_classify=True)
    assert "TURMERIC" in prep.malayalam_expanded
    assert prep.kerala_applied


def test_ocr_typo_cleanup():
    prep = preprocess_retail_query("p cocunut oil 1l", for_classify=False)
    assert "COCONUT" in prep.typo_fixed


def test_expand_kerala_query_matches_preprocess():
    raw = "PUJA OIL 200ML"
    assert expand_kerala_query(raw) == preprocess_retail_query(raw).malayalam_expanded


def test_classify_and_predict_share_preprocess_shape():
    raw = "cherupayar 1kg"
    c = preprocess_retail_query(raw, for_classify=True)
    p = preprocess_retail_query(raw, for_classify=False)
    assert c.malayalam_expanded == p.malayalam_expanded
    assert c.for_classify is True
    assert p.for_classify is False
