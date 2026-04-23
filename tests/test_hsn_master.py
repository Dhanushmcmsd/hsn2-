from collections import Counter

from app.services.hsn_master import _majority_gst_rate, build_hsn_master_records, canonicalize_hsn


def test_canonicalize_hsn_right_pads_hierarchical_codes():
    assert canonicalize_hsn("1905") == "19050000"
    assert canonicalize_hsn("190531") == "19053100"
    assert canonicalize_hsn("19053100") == "19053100"


def test_build_hsn_master_records_uses_official_prefixes_and_majority_gst():
    rows = build_hsn_master_records(
        official_rows=[
            {"raw_hsn_code": "1905", "hsn_code": "19050000", "description": "Bread, pastry, cakes, biscuits", "significance": 4},
            {"raw_hsn_code": "190531", "hsn_code": "19053100", "description": "Sweet biscuits", "significance": 6},
            {"raw_hsn_code": "1101", "hsn_code": "11010000", "description": "Wheat flour", "significance": 4},
        ],
        verified_rows=[
            {"raw_hsn_code": "1101", "hsn_code": "11010000", "description": "Aashirvaad Atta 5kg", "gst_rate": 5.0, "category": None, "significance": 4},
        ],
        batch_rows=[
            {"raw_hsn_code": "19053100", "hsn_code": "19053100", "description": "Cookie 83G", "gst_rate": 5.0, "category": "Bakery", "significance": 8},
            {"raw_hsn_code": "19053100", "hsn_code": "19053100", "description": "Cookie 150G", "gst_rate": 5.0, "category": "Bakery", "significance": 8},
            {"raw_hsn_code": "19053100", "hsn_code": "19053100", "description": "Cookie 40G", "gst_rate": 18.0, "category": "Bakery", "significance": 8},
        ],
    )

    by_code = {row["hsn_code"]: row for row in rows}

    biscuit = by_code["19053100"]
    assert biscuit["description"] == "Sweet biscuits"
    assert biscuit["cbic_description"] == "Sweet biscuits"
    assert biscuit["parent_heading_desc"] == "Bread, pastry, cakes, biscuits"
    assert biscuit["gst_rate"] == 5.0
    assert biscuit["category"] is None

    flour = by_code["11010000"]
    assert flour["description"] == "Wheat flour"
    assert flour["cbic_description"] == "Wheat flour"
    assert flour["parent_heading_desc"] is None
    assert flour["gst_rate"] == 5.0


def test_majority_gst_rate_falls_back_when_only_single_conflicting_votes_exist():
    assert _majority_gst_rate(Counter({5.0: 1, 18.0: 1})) is None
    assert _majority_gst_rate(Counter({5.0: 2, 18.0: 1})) == 5.0
