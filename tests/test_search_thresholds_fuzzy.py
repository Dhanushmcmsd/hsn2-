"""Fuzzy threshold and short-brand safety regression tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.search_thresholds import (
    CLASSIFY_BRAND_SIM_THRESHOLD,
    CLASSIFY_SHORT_BRAND_SIM_THRESHOLD,
    PREDICT_BRAND_SIM_THRESHOLD,
    effective_brand_trgm_min,
)


class TestThresholdConstants:
    def test_classify_stricter_than_predict(self):
        assert CLASSIFY_BRAND_SIM_THRESHOLD > PREDICT_BRAND_SIM_THRESHOLD

    def test_short_brand_raises_classify_floor(self):
        assert effective_brand_trgm_min("SURF", for_classify=True) >= CLASSIFY_SHORT_BRAND_SIM_THRESHOLD
        assert effective_brand_trgm_min("SURF", for_classify=False) < CLASSIFY_SHORT_BRAND_SIM_THRESHOLD


class TestBrandLookupShortTokens:
    @pytest.mark.asyncio
    async def test_milk_passthrough_on_classify(self):
        from app.services.brand_search import brand_lookup

        db = AsyncMock()
        result = await brand_lookup(db, "MILK", min_score=0.65, for_classify=True)
        assert result is None
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_bru_skips_fuzzy_tier(self):
        from app.services import brand_search as bs

        db = AsyncMock()
        with patch.object(bs, "_tier0_alias_lookup", new_callable=AsyncMock, return_value=None), \
             patch.object(bs, "_tier1_exact_brand", new_callable=AsyncMock, return_value=None), \
             patch.object(bs, "_tier2_fuzzy_brand", new_callable=AsyncMock) as mock_fuzzy, \
             patch.object(bs, "_tier3_category_keyword", new_callable=AsyncMock, return_value=None):
            await bs.brand_lookup(db, "BRU", min_score=0.50, for_classify=True)
            mock_fuzzy.assert_not_called()

    @pytest.mark.asyncio
    async def test_classify_fuzzy_uses_high_min_trgm(self):
        from app.services import brand_search as bs

        db = AsyncMock()
        with patch.object(bs, "_tier0_alias_lookup", new_callable=AsyncMock, return_value=None), \
             patch.object(bs, "_tier1_exact_brand", new_callable=AsyncMock, return_value=None), \
             patch.object(bs, "_tier2_fuzzy_brand", new_callable=AsyncMock, return_value=None) as mock_fuzzy, \
             patch.object(bs, "_tier3_category_keyword", new_callable=AsyncMock, return_value=None):
            await bs.brand_lookup(db, "HORLICKS", min_score=0.65, for_classify=True)
            assert mock_fuzzy.called
            _, kwargs = mock_fuzzy.call_args
            assert kwargs["min_trgm"] >= CLASSIFY_BRAND_SIM_THRESHOLD
