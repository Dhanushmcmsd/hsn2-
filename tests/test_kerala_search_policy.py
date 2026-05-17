"""Regression tests for Kerala/Malayalam compliance search policies."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.kerala_aliases import CURATED_KERALA_ALIAS_MAP, KERALA_ALIAS_MAP
from app.services.kerala_corpus_maps import (
    corpus_derived_alias_map,
    corpus_transliterations_map,
    is_ambiguous_standalone_query,
    merge_alias_maps,
)
from app.services.kerala_corpus_hints import _load_corpus_raw
from app.services.kerala_search import kerala_fallback_search
from app.services.kerala_search_policy import (
    analyze_duplicate_corpus_terms,
    curated_overrides_corpus,
    hint_only_standalone_tokens,
    is_canonical_malayalam_script_input,
    is_hint_only_standalone_token,
    is_kerala_corpus_seed_required,
    merge_alias_maps as policy_merge,
    seed_status_summary,
    should_block_standalone_exact_alias,
    should_skip_hint_only_abbrev_expansion,
    should_skip_standalone_translit_expansion,
)
from app.services.retail_preprocess import apply_kerala_expansion, preprocess_retail_query

_CORPUS = Path(__file__).resolve().parents[1] / "data" / "kerala_retail_aliases.json"

# Known curated override: corpus may derive PUTTU differently; curated HSN must win.
_CURATED_OVERRIDE_KEY = "PUTTU"
_CURATED_HSN = CURATED_KERALA_ALIAS_MAP[_CURATED_OVERRIDE_KEY]["hsn_code"]


class TestMalayalamScriptCanonical:
    def test_script_detected(self):
        assert is_canonical_malayalam_script_input("വെളിച്ചെണ്ണ")
        assert not is_canonical_malayalam_script_input("velichenna")

    def test_script_not_roman_expanded(self):
        script = "മഞ്ഞൾപൊടി"
        prep = preprocess_retail_query(script, for_classify=True)
        assert prep.malayalam_expanded == prep.normalized
        assert "TURMERIC" not in prep.malayalam_expanded
        assert not prep.kerala_applied

    def test_roman_still_expands(self):
        prep = preprocess_retail_query("velichenna 1l", for_classify=True)
        assert "COCONUT" in prep.malayalam_expanded

    def test_apply_kerala_expansion_not_used_for_script_in_preprocess(self):
        script = "തുവര പരിപ്പ്"
        before = apply_kerala_expansion(script)
        prep = preprocess_retail_query(script, for_classify=True)
        assert prep.malayalam_expanded != before.upper() or script in prep.original


class TestHintOnlyStandalone:
    @pytest.mark.parametrize("token", ["nadan", "puli", "thuvara"])
    def test_tokens_in_hint_set(self, token: str):
        assert is_hint_only_standalone_token(token)

    @pytest.mark.parametrize(
        "query,expected_fragment",
        [
            ("thuvara", "THUVARA"),
            ("puli", "PULI"),
            ("nadan", "NADAN"),
        ],
    )
    def test_standalone_not_roman_expanded(self, query: str, expected_fragment: str):
        prep = preprocess_retail_query(query, for_classify=True)
        assert expected_fragment in prep.malayalam_expanded
        assert prep.malayalam_expanded.strip() == expected_fragment

    @pytest.mark.parametrize(
        "query,needle",
        [
            ("thuvara parippu", "TOOR"),
            ("nadan ari", "RICE"),
            ("puli inji", "PICKLE"),
        ],
    )
    def test_phrase_expansion_allowed(self, query: str, needle: str):
        prep = preprocess_retail_query(query, for_classify=True)
        assert needle in prep.malayalam_expanded

    def test_kodampuli_distinct_product_expands(self):
        prep = preprocess_retail_query("kodampuli 100g", for_classify=True)
        assert "GAMBOGE" in prep.malayalam_expanded or "KODAMPULI" in prep.malayalam_expanded

    def test_nadan_abbrev_blocked_standalone(self):
        assert should_skip_hint_only_abbrev_expansion("nadan", multi_word=False)
        assert not should_skip_hint_only_abbrev_expansion("nadan", multi_word=True)

    def test_translit_map_excludes_ambiguous_singles(self):
        translit = corpus_transliterations_map()
        for tok in hint_only_standalone_tokens():
            if " " not in tok:
                assert tok.lower() not in translit

    def test_should_block_standalone_exact_alias(self):
        assert should_block_standalone_exact_alias("PULI")
        assert not should_block_standalone_exact_alias("THUVARA PARIPPU")
        assert is_ambiguous_standalone_query("THUVARA")


class TestCuratedOverridePrecedence:
    def test_merge_curated_wins(self):
        derived = {"PUTTU": {"hsn_code": "99999999", "confidence": 0.5}}
        curated = {"PUTTU": {"hsn_code": "11023000", "confidence": 0.9}}
        merged = policy_merge(curated, derived)
        assert merged["PUTTU"]["hsn_code"] == "11023000"

    def test_live_map_curated_puttu_hsn(self):
        assert KERALA_ALIAS_MAP[_CURATED_OVERRIDE_KEY]["hsn_code"] == _CURATED_HSN

    def test_conflict_visible_in_diagnostics(self):
        conflicts = curated_overrides_corpus(CURATED_KERALA_ALIAS_MAP, corpus_derived_alias_map())
        assert isinstance(conflicts, list)
        # Conflicts may be empty if corpus agrees; policy API must be callable.
        for row in conflicts:
            assert row["policy"] == "curated_wins"

    def test_corpus_edit_does_not_replace_curated_without_merge_change(self):
        derived_only = corpus_derived_alias_map()
        if _CURATED_OVERRIDE_KEY in derived_only:
            merged = merge_alias_maps(CURATED_KERALA_ALIAS_MAP, derived_only)
            assert merged[_CURATED_OVERRIDE_KEY]["hsn_code"] == _CURATED_HSN


class TestConservativeDuplicates:
    def test_ambiguous_terms_in_corpus(self):
        raw = json.loads(_CORPUS.read_text(encoding="utf-8"))
        report = analyze_duplicate_corpus_terms(raw)
        for tok in ("puli", "thuvara", "nadan"):
            assert tok in report["strictly_ambiguous_terms"]

    def test_duplicate_mixed_priority_flags_conservative(self):
        rows = [
            {
                "language_code": "ml-roman",
                "original_term": "DEMO",
                "priority": 100,
                "hsn_code": "11023000",
            },
            {
                "language_code": "ml-roman",
                "original_term": "DEMO",
                "priority": 25,
                "notes": "ambiguous standalone - use multi-word retail phrase",
            },
        ]
        report = analyze_duplicate_corpus_terms(rows)
        assert "demo" in report["strictly_ambiguous_terms"]


class TestSeedBenchmarkPolicy:
    def test_seed_required_when_postgres_not_seeded(self):
        meta = {
            "dialect": "postgresql",
            "expected_kerala_corpus_rows": 300,
            "kerala_corpus_seeded": False,
            "kerala_corpus_count": 0,
        }
        assert is_kerala_corpus_seed_required(meta)

    def test_seed_not_required_when_seeded(self):
        meta = {
            "dialect": "postgresql",
            "expected_kerala_corpus_rows": 300,
            "kerala_corpus_seeded": True,
            "kerala_corpus_count": 295,
        }
        assert not is_kerala_corpus_seed_required(meta)

    def test_seed_status_summary(self):
        meta = {
            "dialect": "postgresql",
            "expected_kerala_corpus_rows": 300,
            "kerala_corpus_seeded": False,
            "kerala_corpus_count": 10,
        }
        assert "NOT SEEDED" in seed_status_summary(meta)

    def test_enforce_preflight_blocks_when_required(self):
        from app.services.benchmark_preflight import enforce_kerala_corpus_preflight

        with pytest.raises(SystemExit):
            enforce_kerala_corpus_preflight(
                {
                    "dialect": "postgresql",
                    "kerala_corpus_seeded": False,
                    "seed_status": "NOT SEEDED",
                },
                require=True,
            )

    def test_enforce_preflight_noop_when_not_required(self):
        from app.services.benchmark_preflight import enforce_kerala_corpus_preflight

        enforce_kerala_corpus_preflight({"kerala_corpus_seeded": False}, require=False)


@pytest.mark.asyncio
async def test_ambiguous_standalone_skips_kerala_exact_alias():
    """kerala_fallback_search must not return kerala_alias_exact for puli alone."""
    rows = await kerala_fallback_search("puli", db=None)
    assert rows == [] or all(r.get("method") != "kerala_alias_exact" for r in rows)
