"""Regression tests for gst_classifier production fixes and retail/Malayalam paths."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFinalizeReviewPrecedence:
    """Operator precedence fix in _finalize_layer_result review flag."""

    @pytest.mark.asyncio
    async def test_low_confidence_tier_below_5_no_review_from_confidence(self):
        from app.services.gst_classifier import _finalize_layer_result

        partial = {
            "hsn_code": "19019090",
            "description": "test",
            "confidence": 55,
            "tier_used": 4,
            "source": "keyword_category_map",
            "verified": True,
            "review_required": False,
        }
        with patch(
            "app.services.classifier_layers.enrich_tax_metadata",
            new_callable=AsyncMock,
            return_value={**partial, "rate_conflict": False},
        ):
            out = await _finalize_layer_result(AsyncMock(), partial, 1.0)
        assert out["review_required"] is False

    @pytest.mark.asyncio
    async def test_low_confidence_tier_5_sets_review(self):
        from app.services.gst_classifier import _finalize_layer_result

        partial = {
            "hsn_code": "19019090",
            "description": "test",
            "confidence": 65,
            "tier_used": 5,
            "source": "product_fuzzy",
            "verified": False,
            "review_required": False,
        }
        with patch(
            "app.services.classifier_layers.enrich_tax_metadata",
            new_callable=AsyncMock,
            return_value={**partial, "rate_conflict": False},
        ):
            out = await _finalize_layer_result(AsyncMock(), partial, 1.0)
        assert out["review_required"] is True

    @pytest.mark.asyncio
    async def test_high_confidence_tier_5_no_review(self):
        from app.services.gst_classifier import _finalize_layer_result

        partial = {
            "hsn_code": "19019090",
            "description": "test",
            "confidence": 85,
            "tier_used": 5,
            "source": "product_fuzzy",
            "verified": True,
            "review_required": False,
        }
        with patch(
            "app.services.classifier_layers.enrich_tax_metadata",
            new_callable=AsyncMock,
            return_value={**partial, "rate_conflict": False},
        ):
            out = await _finalize_layer_result(AsyncMock(), partial, 1.0)
        assert out["review_required"] is False

    @pytest.mark.asyncio
    async def test_explicit_review_required_true(self):
        from app.services.gst_classifier import _finalize_layer_result

        partial = {
            "hsn_code": "19019090",
            "description": "test",
            "confidence": 99,
            "tier_used": 1,
            "source": "brand_alias_exact",
            "verified": True,
            "review_required": True,
        }
        with patch(
            "app.services.classifier_layers.enrich_tax_metadata",
            new_callable=AsyncMock,
            return_value={**partial, "rate_conflict": False},
        ):
            out = await _finalize_layer_result(AsyncMock(), partial, 1.0)
        assert out["review_required"] is True


class TestKeywordInvalidHsnGuard:
    @pytest.mark.asyncio
    async def test_invalid_keyword_does_not_finalize_over_better_guess(self):
        from app.services.gst_classifier import classify

        good_guess = {
            "hsn_code": "15131900",
            "description": "Coconut oil",
            "gst_rate": 5.0,
            "cess_applicable": False,
            "confidence": 65,
            "tier_used": 5,
            "source": "product_fuzzy",
            "review_required": True,
        }
        bad_kw = {"hsn_code": "BADCODE", "confidence": 99, "tier_used": 5}

        with patch("app.services.gst_classifier._tier0_cache", return_value=None), \
             patch("app.services.gst_classifier._tier1_exact_brand", return_value=None), \
             patch("app.services.gst_classifier._tier2_exact_product", return_value=None), \
             patch("app.services.hsn_master.get_alias_hsn", return_value=None), \
             patch("app.services.gst_classifier._tier_kerala_retail", new_callable=AsyncMock, return_value=None), \
             patch("app.services.classifier_layers.layer_curated_master", return_value=None), \
             patch("app.services.gst_classifier._tier4_keyword", return_value=None), \
             patch("app.services.gst_classifier._tier5_broad_resolution", return_value=good_guess), \
             patch("app.services.normalizer.extract_product_keywords", return_value=["OIL"]), \
             patch("app.services.pg_search.keyword_hsn_search", new_callable=AsyncMock, return_value=bad_kw), \
             patch("app.services.gst_classifier._tier6_pending_review") as mock_p6, \
             patch("app.services.gst_classifier._finalize_layer_result", new_callable=AsyncMock) as mock_fin:
            mock_p6.return_value = {
                "hsn_code": good_guess["hsn_code"],
                "description": "pending",
                "gst_rate": 5.0,
                "confidence": 40,
                "needs_manual_review": True,
            }
            mock_fin.return_value = {"hsn_code": good_guess["hsn_code"], "review_required": True}
            await classify(AsyncMock(), "unknown xyz sku oil", bypass_cache=True)
            # Pending path should see good_guess HSN, not invalid keyword code
            assert mock_p6.called
            call_kwargs = mock_p6.call_args[0]
            best = call_kwargs[3]
            assert best["hsn_code"] == "15131900"


class TestAliasDictPathLogging:
    @pytest.mark.asyncio
    async def test_alias_hit_finalizes_with_layer_metadata(self):
        from app.services.gst_classifier import classify

        with patch("app.services.gst_classifier._tier0_cache", return_value=None), \
             patch("app.services.gst_classifier._tier1_exact_brand", return_value=None), \
             patch("app.services.gst_classifier._tier2_exact_product", return_value=None), \
             patch("app.services.gst_classifier._tier_kerala_retail", new_callable=AsyncMock, return_value=None), \
             patch("app.services.hsn_master.get_alias_hsn", return_value="151319"), \
             patch("app.services.hsn_master.resolve_alias_gst", return_value=5.0), \
             patch("app.services.gst_classifier._finalize_layer_result", new_callable=AsyncMock) as mock_fin:
            mock_fin.return_value = {"hsn_code": "15131900", "confidence": 98, "matched_layer": "L0_alias_dict"}
            await classify(AsyncMock(), "coconut oil", bypass_cache=True)
            assert mock_fin.called
            partial = mock_fin.call_args[0][1]
            assert partial["matched_layer"] == "L0_alias_dict"
            assert partial["confidence"] == 98
            assert partial["source"] == "L0_alias_dict"


class TestFuzzyThresholds:
    def test_brand_fuzzy_min_sim_constant(self):
        from app.services.search_thresholds import (
            CLASSIFY_BRAND_SIM_THRESHOLD,
            CLASSIFY_PRODUCT_SIM_THRESHOLD,
        )

        assert CLASSIFY_BRAND_SIM_THRESHOLD >= 0.65
        assert CLASSIFY_PRODUCT_SIM_THRESHOLD >= 0.55


class TestKeralaRetailInClassify:
    @pytest.mark.asyncio
    async def test_kerala_alias_exact_wins_in_classify(self):
        from app.services.gst_classifier import classify

        kerala_hit = {
            "hsn_code": "15180040",
            "description": "Puja oil",
            "gst_rate": 5.0,
            "cess_applicable": False,
            "confidence": 96,
            "tier_used": 3,
            "source": "kerala_alias_exact",
            "verified": True,
            "matched_layer": "L0_kerala_retail",
        }

        with patch("app.services.gst_classifier._tier0_cache", return_value=None), \
             patch("app.services.gst_classifier._tier2_exact_product", return_value=None), \
             patch("app.services.hsn_master.get_alias_hsn", return_value=None), \
             patch("app.services.gst_classifier._tier_kerala_retail", new_callable=AsyncMock, return_value=kerala_hit), \
             patch("app.services.gst_classifier._finalize_layer_result", new_callable=AsyncMock) as mock_fin:
            mock_fin.return_value = {**kerala_hit, "hsn_code": "15180040"}
            out = await classify(AsyncMock(), "PUJA OIL", bypass_cache=True)
            assert out["hsn_code"] == "15180040"
            assert mock_fin.called


class TestVerifiedLookupKeys:
    def test_raw_catalog_key_first(self):
        from app.services.gst_classifier import _verified_lookup_keys
        from app.services.retail_preprocess import preprocess_retail_query

        desc = "PEDIASURE CHOCOLATE FLAVOUR 200G REFIL"
        prep = preprocess_retail_query(desc, for_classify=True)
        keys = _verified_lookup_keys(desc, prep)
        assert keys[0] == desc.upper().strip()
        assert "REFIL" in keys[0]

    def test_pachari_brand_not_split_in_preprocess(self):
        from app.services.retail_preprocess import preprocess_retail_query

        prep = preprocess_retail_query("PACHARI REGULAR 2KG", for_classify=True)
        assert "PACHA ARI" not in prep.normalized
        assert "PACHARI" in prep.normalized


class TestRetailNormalization:
    def test_cocunut_typo_expands(self):
        from app.services.normalizer import normalize_product_name

        assert "COCONUT" in normalize_product_name("p cocunut oil 1l")

    def test_malayalam_script_passthrough(self):
        from app.services.normalizer import normalize_product_name

        ml = "\u0d2e\u0d1e\u0d4d\u0d1e\u0d33\u0d4d\u0d2a\u0d4b\u0d1f\u0d3f"
        assert normalize_product_name(ml) == ml

    def test_expand_kerala_manjal_roman(self):
        from app.services.kerala_search import expand_kerala_query

        expanded = expand_kerala_query("manjal podi 100g")
        assert "TURMERIC" in expanded

    def test_in_memory_alias_parle_g(self):
        from app.services.hsn_master import get_alias_hsn

        assert get_alias_hsn("parle g small") == "190531"
