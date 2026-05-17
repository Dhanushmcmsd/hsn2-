"""Single /predict and /hsn/batch share gst_classifier via classify_adapter."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.classify_adapter import is_authoritative_classify, to_batch_result


class TestClassifyAdapter:
    def test_authoritative_verified_hit(self):
        out = {
            "hsn_code": "19019090",
            "gst_rate": 18.0,
            "confidence": 99,
            "review_required": False,
            "needs_manual_review": False,
        }
        assert is_authoritative_classify(out) is True

    def test_review_flag_not_authoritative(self):
        out = {
            "hsn_code": "19019090",
            "gst_rate": 18.0,
            "confidence": 99,
            "review_required": True,
        }
        assert is_authoritative_classify(out) is False

    def test_batch_row_shape(self):
        row = to_batch_result("HORLICKS 400G", {
            "hsn_code": "19019090",
            "description": "Malt food",
            "gst_rate": 18.0,
            "confidence": 99,
            "matched_layer": "L0_verified_product",
            "review_required": False,
        })
        assert row["hsn_code"] == "19019090"
        assert row["confidence"] >= 0.99
        assert row["match_method"] == "L0_verified_product"


def test_predict_from_bulk_cached_row():
    from app.routes.predict import _predict_from_cached

    hit = _predict_from_cached(
        {
            "query": "PACHARI REGULAR 2KG",
            "hsn_code": "07139000",
            "description": "Pachari rice",
            "gst_rate": 5.0,
            "confidence": 0.99,
            "match_method": "L0_verified_product",
            "alternatives": [],
        },
        request_id="req-1",
        input_text="PACHARI REGULAR 2KG",
    )
    assert hit is not None
    assert hit.top_match.hsn_code == "07139000"


@pytest.mark.asyncio
async def test_batch_endpoint_uses_classify():
    from app.routes.predict import batch_predict
    from app.models.schemas import BatchQuery

    classify_out = {
        "hsn_code": "07139000",
        "description": "Pachari rice",
        "gst_rate": 5.0,
        "confidence": 99,
        "matched_layer": "L0_verified_product",
        "review_required": False,
        "needs_manual_review": False,
        "alternates": [],
    }

    with patch("app.routes.predict.check_rate_limit", new_callable=AsyncMock), \
         patch("app.routes.predict.get_cache", new_callable=AsyncMock, return_value=None), \
         patch("app.routes.predict.set_cache", new_callable=AsyncMock), \
         patch("app.services.gst_classifier.classify", new_callable=AsyncMock, return_value=classify_out):
        resp = await batch_predict(BatchQuery(queries=["PACHARI REGULAR 2KG"]), api_key="test-key")

    assert resp.total == 1
    assert resp.matched == 1
    assert resp.results[0].hsn_code == "07139000"
