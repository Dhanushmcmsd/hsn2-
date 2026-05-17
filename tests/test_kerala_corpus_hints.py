"""Tests for Kerala corpus-driven preprocess hints."""
from __future__ import annotations

from app.services.kerala_corpus_hints import (
    corpus_joined_forms,
    corpus_stats,
    corpus_transliterations,
    is_romanized_malayalam_retail,
)
from app.services.retail_preprocess import preprocess_retail_query


def test_corpus_stats_populated():
    stats = corpus_stats()
    assert stats["corpus_path_exists"]
    assert stats["total_rows"] >= 280
    assert stats["transliteration_hints"] >= 80


def test_joined_forms_include_manjalpodi():
    joined = {a: b for a, b in corpus_joined_forms()}
    assert "manjalpodi" in joined


def test_corpus_transliteration_used_in_preprocess():
    hints = corpus_transliterations()
    assert "velichenna" in hints
    prep = preprocess_retail_query("velichenna 500ml")
    assert "COCONUT" in prep.malayalam_expanded


def test_romanized_detection_negative_for_generic_english():
    assert not is_romanized_malayalam_retail("COLGATE TOOTHPASTE 100G")
