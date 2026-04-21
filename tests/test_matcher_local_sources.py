from collections import defaultdict

from app.services.dataset import load_dataset
from app.services.matcher import (
    HybridMatcher,
    _normalize_for_match,
    expand_fmcg_abbreviations,
    extract_core_product,
    strip_sizes,
)


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
        expanded_norm = _normalize_for_match(row["description"])
        if expanded_norm != row["description_normalized"]:
            matcher._exact_map[expanded_norm].append(row)
        matcher._no_size_map[row["description_no_size"]].append(row)
        expanded_no_size = strip_sizes(expand_fmcg_abbreviations(row["description"]))
        if expanded_no_size and expanded_no_size != row["description_no_size"]:
            matcher._no_size_map[expanded_no_size].append(row)
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


def test_match_prefers_supported_size_matching_jam_family():
    rows = [
        {
            "hsn_code": "20079990",
            "description": "HAPPY MIXED FRUIT JAM 350G",
            "source": "product_batch",
            "gst_rate": "5",
            "category": "Jams_Spreads",
            "description_normalized": "HAPPY MIXED FRUIT JAM 350G",
            "description_no_size": "HAPPY MIXED FRUIT JAM",
            "aliases": [],
        },
        {
            "hsn_code": "20079990",
            "description": "HAPPY MIXED FRUIT JAM 500G",
            "source": "product_batch",
            "gst_rate": "12",
            "category": "Jams_Spreads",
            "description_normalized": "HAPPY MIXED FRUIT JAM 500G",
            "description_no_size": "HAPPY MIXED FRUIT JAM",
            "aliases": [],
        },
        {
            "hsn_code": "20079910",
            "description": "GRANDMAS JACKFRUIT JAM 350G",
            "source": "product_batch",
            "gst_rate": "5",
            "category": "Jams_Spreads",
            "description_normalized": "GRANDMAS JACKFRUIT JAM 350G",
            "description_no_size": "GRANDMAS JACKFRUIT JAM",
            "aliases": [],
        },
    ]
    matcher = _build_matcher(rows)

    results = matcher.match("FRUIT JAM 350g")

    assert results[0]["hsn_code"] == "20079990"
    assert "FRUIT JAM 350G" in results[0]["description"]


def test_match_keeps_pure_puja_oil_on_puja_oil_family():
    rows = [
        {
            "hsn_code": "15180040",
            "description": "OM SHANTHI JASMINE PURE PUJA OIL 200ML",
            "source": "product_batch",
            "gst_rate": "5",
            "category": "Edible_Oils",
            "description_normalized": "OM SHANTHI JASMINE PURE PUJA OIL 200ML",
            "description_no_size": "OM SHANTHI JASMINE PURE PUJA OIL",
            "aliases": [],
        },
        {
            "hsn_code": "15180040",
            "description": "OM SHANTHI PARIJTA PURE PUJA OIL 500ML",
            "source": "product_batch",
            "gst_rate": "5",
            "category": "Edible_Oils",
            "description_normalized": "OM SHANTHI PARIJTA PURE PUJA OIL 500ML",
            "description_no_size": "OM SHANTHI PARIJTA PURE PUJA OIL",
            "aliases": [],
        },
        {
            "hsn_code": "15131900",
            "description": "PALM OIL 1LTR",
            "source": "product_batch",
            "gst_rate": "5",
            "category": "Edible_Oils",
            "description_normalized": "PALM OIL 1LTR",
            "description_no_size": "PALM OIL",
            "aliases": [],
        },
    ]
    matcher = _build_matcher(rows)

    results = matcher.match("PURE PUJA OIL")

    assert results[0]["hsn_code"] == "15180040"
    assert "PUJA OIL" in results[0]["description"]
