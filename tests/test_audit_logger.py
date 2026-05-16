"""Tests for structured classify audit logging."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_classify_writes_audit_log(client, api_key, tmp_path):
    audit_file = tmp_path / "audit.jsonl"
    mock_result = {
        "hsn_code": "19019090",
        "description": "Malted milk food preparations",
        "gst_rate": 18.0,
        "cess_applicable": False,
        "confidence": 99,
        "tier_used": 1,
        "source": "brand_alias_exact",
        "verified": True,
        "last_updated": None,
        "elapsed_ms": 12.5,
        "needs_manual_review": False,
        "confidence_score": 99,
        "matched_layer": "tier1",
    }

    with patch("app.services.audit_logger._AUDIT_PATH", audit_file), \
         patch("app.services.gst_classifier.classify", new_callable=AsyncMock) as mock_classify:
        mock_classify.return_value = mock_result
        resp = await client.post(
            "/api/v1/classify",
            json={"query": "BOOST"},
            headers={"X-API-Key": api_key, "X-Request-ID": "test-req-001"},
        )

    assert resp.status_code == 200
    assert audit_file.is_file()

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    entry = json.loads(lines[-1])

    required = {
        "timestamp",
        "request_id",
        "api_key_hash",
        "client_ip",
        "product_name",
        "hsn_code",
        "gst_rate",
        "confidence_score",
        "layer_matched",
        "response_time_ms",
    }
    assert required.issubset(entry.keys())
    assert entry["product_name"] == "BOOST"
    assert entry["hsn_code"] == "19019090"
    assert entry["gst_rate"] == 18.0
    assert entry["confidence_score"] == 99
    assert entry["request_id"] == "test-req-001"
    assert len(entry["api_key_hash"]) == 64
