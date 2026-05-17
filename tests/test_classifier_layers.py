"""Layer precedence and tax-metadata helpers for the classify pipeline."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCodeTypeHelpers:
    def test_sac_not_padded_to_8_digits(self):
        from app.services.classifier_layers import normalize_display_code, code_type_for

        assert code_type_for("9971") == "SAC"
        assert normalize_display_code("9971", code_type="SAC") == "9971"
        assert normalize_display_code("9971") != "99710000"

    def test_hsn_pads_to_8_for_goods(self):
        from app.services.classifier_layers import normalize_display_code

        assert normalize_display_code("190190", code_type="HSN") == "19019000"


class TestAliasWordBoundary:
    def test_short_alias_does_not_match_inside_word(self):
        from app.services.hsn_master import get_alias_hsn

        assert get_alias_hsn("steak") is None
        assert get_alias_hsn("mosquito coil") == "380891"
        assert get_alias_hsn("aluminium foil") is None

    def test_long_alias_still_matches_with_size_suffix(self):
        from app.services.hsn_master import get_alias_hsn

        assert get_alias_hsn("SHUDDHAKERA P.COCONUT OIL 1Ltr") == "151319"


class TestEffectiveTotalTax:
    def test_igst_plus_cess(self):
        from app.services.classifier_layers import _effective_total_tax

        total = _effective_total_tax(28.0, 12.0, tax_semantics="igst_only")
        assert total == 40.0

    @pytest.mark.asyncio
    async def test_enrich_22021000_policy1(self):
        from app.services.classifier_layers import enrich_tax_metadata

        goods_row = {
            "hsn_code": "22021000",
            "description": "Aerated beverages",
            "gst_rate": 28.0,
            "cess_applicable": True,
            "cess_rate": 12.0,
            "rate_semantics": "igst_only",
            "scope": "curated_core",
            "code_kind": "HSN",
            "verified_source": "CBIC",
            "history_gst": 40.0,
        }

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = goods_row
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        out = await enrich_tax_metadata(mock_db, "22021000", partial={})
        assert out["gst_rate"] == 28.0
        assert out["cess_rate"] == 12.0
        assert out["effective_total_tax"] == 40.0
        assert out["tax_semantics"] == "igst_only"
        assert out["rate_conflict"] is False


class TestLayerPrecedence:
    @pytest.mark.asyncio
    async def test_brand_beats_curated(self):
        from app.services.gst_classifier import classify

        brand_hit = {
            "hsn_code": "19019090",
            "description": "Malted milk",
            "gst_rate": 18.0,
            "cess_applicable": False,
            "confidence": 99,
            "tier_used": 1,
            "source": "brand_alias_exact",
            "verified": True,
            "matched_layer": "L1_brand_alias",
            "code_kind": "HSN",
        }

        with patch("app.services.gst_classifier._tier0_cache", return_value=None), \
             patch("app.services.gst_classifier._tier1_exact_brand", return_value=brand_hit), \
             patch("app.services.gst_classifier._tier2_exact_product", return_value=None), \
             patch("app.services.classifier_layers.layer_curated_master", return_value=None), \
             patch("app.services.gst_classifier._finalize_layer_result") as mock_fin:
            mock_fin.return_value = {**brand_hit, "tier_used": 1, "matched_layer": "L1_brand_alias"}
            mock_db = AsyncMock()
            out = await classify(mock_db, "BOOST", bypass_cache=True)
            assert mock_fin.called
            assert out["tier_used"] == 1

    @pytest.mark.asyncio
    async def test_verified_beats_curated(self):
        from app.services.gst_classifier import classify

        product_hit = {
            "hsn_code": "19023000",
            "description": "Noodles",
            "gst_rate": 12.0,
            "cess_applicable": False,
            "confidence": 99,
            "tier_used": 2,
            "source": "verified_product_exact",
            "verified": True,
        }

        with patch("app.services.gst_classifier._tier0_cache", return_value=None), \
             patch("app.services.gst_classifier._tier1_exact_brand", return_value=None), \
             patch("app.services.gst_classifier._tier2_exact_product", return_value=product_hit), \
             patch("app.services.classifier_layers.layer_curated_master", return_value=None), \
             patch("app.services.gst_classifier._finalize_layer_result") as mock_fin:
            mock_fin.return_value = {**product_hit, "tier_used": 2}
            mock_db = AsyncMock()
            out = await classify(mock_db, "MAGGI NOODLES", bypass_cache=True)
            assert out["tier_used"] == 2

    @pytest.mark.asyncio
    async def test_curated_beats_tariff_in_classify(self):
        from app.services.gst_classifier import classify

        curated = {
            "hsn_code": "19019090",
            "description": "Health drink",
            "gst_rate": 18.0,
            "cess_applicable": False,
            "confidence": 85,
            "tier_used": 3,
            "source": "curated_master_fuzzy",
            "verified": True,
        }

        with patch("app.services.gst_classifier._tier0_cache", return_value=None), \
             patch("app.services.gst_classifier._tier1_exact_brand", return_value=None), \
             patch("app.services.gst_classifier._tier2_exact_product", return_value=None), \
             patch("app.services.classifier_layers.layer_curated_master", return_value=curated), \
             patch("app.services.classifier_layers.layer_tariff_fallback") as mock_tariff, \
             patch("app.services.gst_classifier._finalize_layer_result") as mock_fin:
            mock_fin.return_value = {**curated, "matched_layer": "L3_curated_master"}
            mock_db = AsyncMock()
            out = await classify(mock_db, "health drink powder", bypass_cache=True)
            assert out["tier_used"] == 3
            mock_tariff.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_confidence_fuzzy_goes_to_pending_path(self):
        from app.services.gst_classifier import classify

        low_fuzzy = {
            "hsn_code": "99999999",
            "description": "guess",
            "gst_rate": 18.0,
            "cess_applicable": False,
            "confidence": 55,
            "tier_used": 5,
            "source": "product_fuzzy",
            "review_required": True,
        }

        with patch("app.services.gst_classifier._tier0_cache", return_value=None), \
             patch("app.services.gst_classifier._tier1_exact_brand", return_value=None), \
             patch("app.services.gst_classifier._tier2_exact_product", return_value=None), \
             patch("app.services.classifier_layers.layer_curated_master", return_value=None), \
             patch("app.services.gst_classifier._tier4_keyword", return_value=None), \
             patch("app.services.gst_classifier._tier5_broad_resolution", return_value=low_fuzzy), \
             patch("app.services.gst_classifier._tier6_pending_review") as mock_p6, \
             patch("app.services.gst_classifier._finalize_layer_result") as mock_fin:
            mock_p6.return_value = {
                "hsn_code": low_fuzzy["hsn_code"],
                "description": "Approximate",
                "gst_rate": 18.0,
                "confidence": 40,
                "needs_manual_review": True,
            }
            mock_fin.return_value = {
                "hsn_code": low_fuzzy["hsn_code"],
                "needs_manual_review": True,
                "review_required": True,
                "tier_used": 6,
                "matched_layer": "L6_pending_review",
            }
            mock_db = AsyncMock()
            out = await classify(mock_db, "unknown xyz product", bypass_cache=True)
            assert mock_p6.called
            assert out.get("needs_manual_review") is True


class TestSacBrandMetadata:
    @pytest.mark.asyncio
    async def test_brand_sac_code_kind(self):
        from app.services.gst_classifier import _tier1_exact_brand

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: {
            "hsn_code": "9971",
            "category": "Insurance",
            "gst_rate": 18.0,
            "cess_applicable": False,
            "verified_source": "CBIC SAC",
            "brand_name": "LIC",
            "code_kind": "SAC",
            "hm_description": None,
            "sm_description": "Financial services",
            "sm_gst_rate": 18.0,
        }[key]
        mock_row.get = lambda key, default=None: mock_row[key] if key in (
            "code_kind", "sm_description", "hm_description", "sm_gst_rate",
        ) else default

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = mock_row
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _tier1_exact_brand(mock_db, "LIC")
        assert result["hsn_code"] == "9971"
        assert result["code_kind"] == "SAC"
        assert len(result["hsn_code"]) == 4
