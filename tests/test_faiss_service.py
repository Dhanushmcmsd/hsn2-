"""Tests for background FAISS singleton — cold skip, warm search, lock, classify metadata."""
from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.services import faiss_service as fs_mod
from app.services.faiss_service import FAISSService, get_faiss_service


@pytest.fixture(autouse=True)
def _reset_faiss_singleton():
    fs_mod._service = None
    os.environ.pop("FAISS_DISABLED", None)
    yield
    fs_mod._service = None
    os.environ.pop("FAISS_DISABLED", None)


def test_cold_faiss_does_not_block_search_path():
    svc = FAISSService()
    assert not svc.is_ready()
    assert svc.search_text("soap", 3) is None


def test_start_warmup_single_load_under_concurrent_calls():
    svc = FAISSService()
    load_count = {"n": 0}

    def fake_build():
        load_count["n"] += 1
        time.sleep(0.05)
        svc._dataset = [{"hsn_code": "34011190", "description": "SOAP", "gst_rate": "18"}]
        svc._index = MagicMock()
        svc._index.search.return_value = (np.array([[0.9]]), np.array([[0]]))
        svc._model = MagicMock()
        svc._model.encode.return_value = np.array([[1.0, 0.0]], dtype=np.float32)

    with patch.object(svc, "_build_index", side_effect=fake_build):
        threads = [threading.Thread(target=svc.start_warmup) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)
        deadline = time.time() + 2
        while not svc.ready and time.time() < deadline:
            time.sleep(0.01)
    assert svc.ready
    assert load_count["n"] == 1


def test_failed_load_search_returns_none():
    svc = FAISSService()
    with patch.object(svc, "_build_index", side_effect=RuntimeError("boom")):
        svc.start_warmup()
        deadline = time.time() + 2
        while svc.loading and time.time() < deadline:
            time.sleep(0.01)
    assert svc.failed
    assert not svc.is_ready()
    assert svc.search_text("soap", 3) is None


def test_warm_search_returns_results():
    svc = FAISSService()
    svc._dataset = [
        {"hsn_code": "34011190", "description": "BATH SOAP", "gst_rate": "18"},
        {"hsn_code": "33051010", "description": "SHAMPOO", "gst_rate": "18"},
    ]
    svc._model = MagicMock()
    svc._model.encode.return_value = np.array([[1.0, 0.0]], dtype=np.float32)
    svc._index = MagicMock()
    svc._index.search.return_value = (np.array([[0.88, 0.4]]), np.array([[0, 1]]))
    svc.ready = True

    rows = svc.search_text("soap", 2)
    assert rows is not None
    assert len(rows) == 2
    assert rows[0]["hsn_code"] == "34011190"


@pytest.mark.asyncio
async def test_classify_result_includes_faiss_status():
    from app.services.gst_classifier import _make_result

    partial = _make_result(
        "34011190",
        "SOAP",
        18.0,
        False,
        75,
        5,
        "multi_layer_search",
        False,
        12.0,
        faiss_status="cold_skipped",
    )
    assert partial["faiss_status"] == "cold_skipped"


@pytest.mark.asyncio
async def test_layer_faiss_cold_skip_fast():
    from app.services.multi_layer_search import _layer_faiss

    rows, status = await _layer_faiss("bath soap", 3)
    assert rows == []
    assert status == "cold_skipped"


def test_skip_faiss_env_disables_warmup():
    os.environ["FAISS_DISABLED"] = "1"
    svc = get_faiss_service()
    with patch.object(svc, "_build_index") as build:
        svc.start_warmup()
        time.sleep(0.05)
        build.assert_not_called()
    assert not svc.ready
