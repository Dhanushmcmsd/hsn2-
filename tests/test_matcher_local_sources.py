from collections import defaultdict

from app.services.dataset import load_dataset
from app.services.matcher import HybridMatcher, extract_core_product


def _build_matcher(rows):
    matcher = HybridMatcher.__new__(HybridMatcher)
    matcher._dataset = rows
    matcher._embeddings = None
    matcher._model = None
    matcher._ready = False
    matcher._exact_map = defaultdict(list)
    matcher._no_size_map = defaultdict(list)
    for row in rows:
        matcher._exact_map[row["description_normalized"]].append(row)
        matcher._no_size_map[row["description_no_size"]].append(row)
    return matcher


def test_load_dataset_merges_hsn_master_batches_and_verified_rows():
    rows = load_dataset()
    sources = {row["source"] for row in rows}

    assert "hsn_codes" in sources
    assert "product_batch" in sources
    assert "correct_datas" in sources
    assert any(row["description"] == "AMUL PROCESSED CHEESE SLICES 100G" for row in rows)
    assert any(row["description"] == "Wheat Flour" for row in rows)


def test_match_prefers_product_batch_for_exact_product_description():
    rows = [
        {
            "hsn_code": "04063000",
            "description": "AMUL PROCESSED CHEESE SLICES 100G",
            "source": "product_batch",
            "gst_rate": "5",
            "category": "Dairy",
            "description_normalized": "AMUL PROCESSED CHEESE SLICES 100G",
            "description_no_size": "AMUL PROCESSED CHEESE SLICES",
            "aliases": [],
        },
        {
            "hsn_code": "04063000",
            "description": "Cheese",
            "source": "hsn_codes",
            "gst_rate": "",
            "category": "",
            "description_normalized": "CHEESE",
            "description_no_size": "CHEESE",
            "aliases": [],
        },
    ]
    matcher = _build_matcher(rows)

    results = matcher.match("AMUL PROCESSED CHEESE SLICES 100G")

    assert results[0]["hsn_code"] == "04063000"
    assert results[0]["description"] == "AMUL PROCESSED CHEESE SLICES 100G"
    assert results[0]["method"] == "product_batch_exact"
    assert results[0]["score"] >= 0.9


def test_match_uses_verified_excel_rows_for_simple_invoice_terms():
    rows = [
        {
            "hsn_code": "00011001",
            "description": "Wheat Flour",
            "source": "correct_datas",
            "gst_rate": "0",
            "category": "",
            "description_normalized": "WHEAT FLOUR",
            "description_no_size": "WHEAT FLOUR",
            "aliases": [],
        },
        {
            "hsn_code": "00011002",
            "description": "Prepared flour mixes",
            "source": "hsn_codes",
            "gst_rate": "",
            "category": "",
            "description_normalized": "PREPARED FLOUR MIXES",
            "description_no_size": "PREPARED FLOUR MIXES",
            "aliases": [],
        },
    ]
    matcher = _build_matcher(rows)

    results = matcher.match("Wheat Flour")

    assert results[0]["hsn_code"] == "00011001"
    assert results[0]["method"] == "correct_datas_exact"
    assert results[0]["score"] >= 0.95


def test_extract_core_product_still_returns_last_meaningful_term():
    assert extract_core_product("Kitchen Treasure turmeric powder 500g") == "powder"
