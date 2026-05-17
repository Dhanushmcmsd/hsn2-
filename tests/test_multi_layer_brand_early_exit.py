"""Route-aware L0b brand early-exit in multi_layer_search."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.search_thresholds import brand_early_exit_min_score


class TestMultiLayerBrandEarlyExit:
    @pytest.mark.asyncio
    async def test_classify_skips_brand_early_exit_for_malayalam(self):
        from app.services import multi_layer_search as mls
        from app.services.aliases import ExpansionResult

        db = AsyncMock()
        expanded = ExpansionResult(
            original="manjal podi",
            detected_language="ml",
            english_query="turmeric powder",
        )
        with patch.object(mls.aliases_service, "expand_query", new_callable=AsyncMock, return_value=expanded), \
             patch.object(mls, "brand_lookup", new_callable=AsyncMock) as mock_brand, \
             patch.object(mls, "lru_get", return_value=None), \
             patch.object(mls, "get_cache", new_callable=AsyncMock, return_value=None), \
             patch.object(mls, "_layer_verified", new_callable=AsyncMock, return_value=[]), \
             patch.object(mls, "_bounded", new_callable=AsyncMock, return_value=[]):
            await mls.multi_search(db, "manjal podi", bypass_cache=True, for_classify=True)
            mock_brand.assert_not_called()

    @pytest.mark.asyncio
    async def test_predict_calls_brand_lookup_with_lower_floor(self):
        from app.services import multi_layer_search as mls
        from app.services.aliases import ExpansionResult

        db = AsyncMock()
        expanded = ExpansionResult(
            original="HORLICKS 500G",
            detected_language="en",
            english_query="HORLICKS 500G",
        )
        brand_hit = {
            "hsn_code": "19011090",
            "description": "malted milk",
            "score": 0.85,
            "method": "brand_lookup",
        }
        with patch.object(mls.aliases_service, "expand_query", new_callable=AsyncMock, return_value=expanded), \
             patch.object(mls, "brand_lookup", new_callable=AsyncMock, return_value=brand_hit) as mock_brand, \
             patch.object(mls, "lru_get", return_value=None), \
             patch.object(mls, "get_cache", new_callable=AsyncMock, return_value=None):
            out = await mls.multi_search(
                db, "HORLICKS 500G", bypass_cache=True, for_classify=False,
            )
            assert out.results
            mock_brand.assert_called_once()
            assert mock_brand.call_args.kwargs["min_score"] == brand_early_exit_min_score(
                "HORLICKS", for_classify=False,
            )
