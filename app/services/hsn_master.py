from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import structlog

log = structlog.get_logger()

_DATA_PATH = Path(os.getenv("HSN_DATA_PATH", "data/hsn_codes.csv"))
_VERIFIED_DATA_PATH = Path(os.getenv("VERIFIED_DATA_PATH", "data/correct_datas.xlsx"))
_PRODUCT_BATCH_DIR = Path(os.getenv("PRODUCT_BATCH_DIR", "data/product_batches"))

_XL_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

_GST_QUALIFIER_TOKENS = (
    "branded",
    "unit container",
    "retail sale",
    "<=rs.500",
    "commercial use",
    "dog/cat food",
)


def canonicalize_hsn(code: object) -> str:
    digits = re.sub(r"[^0-9]", "", str(code or "").strip())
    if not digits:
        return ""
    if len(digits) >= 8:
        return digits[:8]
    if len(digits) in {2, 4, 6}:
        return digits.ljust(8, "0")
    return digits.zfill(8)



# ── Chapter-level GST rate fallback (CBIC schedule, 2024) ────────────────────
# Used when no product-specific rate is found in xlsx/batch data.
# Keys are 2-digit chapter codes (strings). Values are GST % (float).
_CHAPTER_GST_RATES: dict[str, float] = {
    # Section I — Live animals, animal products
    "01": 0.0, "02": 0.0, "03": 5.0, "04": 5.0, "05": 0.0,
    # Section II — Vegetable products
    "06": 5.0, "07": 0.0, "08": 0.0, "09": 0.0, "10": 0.0,
    "11": 0.0, "12": 0.0, "13": 5.0, "14": 0.0,
    # Section III — Animal/veg fats and oils
    "15": 5.0,
    # Section IV — Prepared foodstuffs
    "16": 12.0, "17": 5.0, "18": 18.0, "19": 18.0, "20": 12.0,
    "21": 18.0, "22": 18.0, "23": 0.0, "24": 28.0,
    # Section V — Mineral products
    "25": 5.0, "26": 5.0, "27": 5.0,
    # Section VI — Chemical/allied industries
    "28": 18.0, "29": 18.0, "30": 12.0, "31": 5.0, "32": 18.0,
    "33": 18.0, "34": 18.0, "35": 18.0, "36": 18.0, "37": 18.0,
    "38": 18.0,
    # Section VII — Plastics and rubber
    "39": 18.0, "40": 12.0,
    # Section VIII — Hides, skins, leather
    "41": 5.0, "42": 12.0, "43": 12.0,
    # Section IX — Wood and articles
    "44": 12.0, "45": 12.0, "46": 12.0,
    # Section X — Pulp, paper
    "47": 12.0, "48": 12.0, "49": 12.0,
    # Section XI — Textiles
    "50": 5.0, "51": 5.0, "52": 5.0, "53": 5.0, "54": 5.0,
    "55": 5.0, "56": 5.0, "57": 5.0, "58": 5.0, "59": 12.0,
    "60": 5.0, "61": 5.0, "62": 5.0, "63": 5.0,
    # Section XII — Footwear, headgear
    "64": 12.0, "65": 12.0, "66": 12.0, "67": 12.0,
    # Section XIII — Stone, plaster, cement, glass
    "68": 12.0, "69": 12.0, "70": 18.0,
    # Section XIV — Precious metals
    "71": 3.0,
    # Section XV — Base metals
    "72": 18.0, "73": 18.0, "74": 18.0, "75": 18.0, "76": 18.0,
    "77": 18.0, "78": 18.0, "79": 18.0, "80": 18.0, "81": 18.0,
    "82": 18.0, "83": 18.0,
    # Section XVI — Machinery/electrical
    "84": 18.0, "85": 18.0,
    # Section XVII — Vehicles, aircraft, vessels
    "86": 12.0, "87": 28.0, "88": 18.0, "89": 5.0,
    # Section XVIII — Optical, watches, medical
    "90": 12.0, "91": 18.0, "92": 18.0,
    # Section XIX — Arms and ammo
    "93": 12.0,
    # Section XX — Miscellaneous manufactured articles
    "94": 18.0, "95": 18.0, "96": 18.0,
    # Section XXI — Works of art
    "97": 12.0, "98": 5.0, "99": 0.0,
}


def _chapter_gst_fallback(hsn_code: str) -> float | None:
    """Return chapter-level GST rate for codes where no product-specific rate exists."""
    chapter = hsn_code[:2] if len(hsn_code) >= 2 else ""
    return _CHAPTER_GST_RATES.get(chapter)


def _clean_gst(raw: object) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", str(raw or ""))
    return float(match.group(1)) if match else None


def _normalise_category(raw: object) -> str | None:
    value = str(raw or "").strip()
    if not value or value == "Other_Unclassified":
        return None
    return value


def _read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with ZipFile(path) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")

    root = ET.fromstring(sheet_xml)
    rows: list[list[str]] = []
    for row_node in root.findall(".//x:sheetData/x:row", _XL_NS):
        values: list[str] = []
        for cell in row_node.findall("x:c", _XL_NS):
            inline = cell.find("x:is/x:t", _XL_NS)
            if inline is not None:
                values.append(inline.text or "")
                continue
            value = cell.find("x:v", _XL_NS)
            values.append(value.text if value is not None else "")
        rows.append(values)

    if not rows:
        return []

    headers = [str(v or "").strip() for v in rows[0]]
    data_rows: list[dict[str, str]] = []
    for row in rows[1:]:
        padded = row + [""] * max(0, len(headers) - len(row))
        data_rows.append({headers[idx]: padded[idx] for idx in range(len(headers))})
    return data_rows


# ── Verified Indian product → HSN aliases (CBIC-confirmed) ────────────────────
# These supplement the Excel verified data file with hard-coded high-confidence
# product type mappings so common searches never fall back to TIER 6.
_VERIFIED_PRODUCT_ALIASES: dict[str, str] = {
    # FMCG brands (client Excel high-frequency undetected)
    "horlicks": "190190",
    "boost": "190190",
    "bournvita": "190190",
    "complan": "190190",
    "britannia": "190531",
    "sunfeast": "190531",
    "yippee": "190230",
    "vkc": "640199",
    "himalaya": "330499",
    "nivea": "330499",
    "gillette": "821210",
    "yardley": "330300",
    "dabur": "300490",
    "patanjali": "300490",
    # Biscuits / Bakery
    "good day": "190531",
    "good day biscuit": "190531",
    "parle g": "190531",
    "parle-g": "190531",
    "marie gold": "190531",
    "marie biscuit": "190531",
    "bourbon biscuit": "190531",
    "hide and seek": "190531",
    "oreo": "190531",
    "cream biscuit": "190531",
    "glucose biscuit": "190531",
    "digestive biscuit": "190531",
    "cracker biscuit": "190531",
    "wafer biscuit": "190532",
    "waffle": "190532",
    # Papad (HSN 19059040 — CBIC nil-rated papad)
    "papad": "19059040",
    "pappad": "19059040",
    "pappadam": "19059040",
    "apalam": "19059040",
    "khakhra": "19059040",
    "lijjat papad": "19059040",
    # Broom / household
    "broom": "960310",
    "jhadoo": "960310",
    "jhadu": "960310",
    "mosquito coil": "380891",
    "mosquito repellent": "380891",
    "good knight": "380891",
    "incense stick": "330741",
    "incense sticks": "330741",
    "agarbatti": "330741",
    "agarbathi": "330741",
    "phenyl": "340220",
    # South Indian staples / masala
    "puttu podi": "110100",
    "puttupodi": "110100",
    "sambar powder": "091091",
    "sambar pdr": "091091",
    "sambhar powder": "091091",
    "rava idli mix": "19059090",
    "idli mix": "19059090",
    "turmeric powder": "091030",
    "haldi powder": "091030",
    "chilly powder": "090422",
    "chili powder": "090422",
    "chilli powder": "090422",
    "tea powder": "090230",
    "salt": "250100",
    "pink salt": "250100",
    "himalayan salt": "250100",
    "wheat": "100610",
    "mandi rice": "100630",
    "coconut water": "200990",
    "mango juice": "200989",
    "mixed fruit juice": "200989",
    "maggi noodles": "19023090",
    "maggi": "19023090",
    "noodles": "19023090",
    "tomato ketchup": "210320",
    "ketchup": "210320",
    "vada parippu": "071331",
    "parippu": "071331",
    "urad dal": "071331",
    "hershey": "180690",
    "hersheys": "180690",
    "kisses": "180690",
    # Spices / Masala
    "cumin": "090921",
    "jeera": "090921",
    "cumin seeds": "090921",
    "jeera seeds": "090921",
    "black pepper": "090931",
    "pepper": "090931",
    "cardamom": "090831",
    "elaichi": "090831",
    "cinnamon": "090611",
    "dalchini": "090611",
    "cloves": "090711",
    "lavang": "090711",
    "turmeric": "091030",
    "haldi": "091030",
    "chilli powder": "090422",
    "red chilli": "090421",
    "coriander powder": "091021",
    "coriander seeds": "090920",
    "mustard seeds": "120910",
    # Soup / Rasam
    "rasam": "210410",
    "rasam soup": "210410",
    "soup": "210410",
    "tomato soup": "210410",
    "mushroom soup": "210410",
    "instant soup": "210410",
    "knorr soup": "210410",
    "maggi soup": "210410",
    # Footwear
    "slipper": "640291",
    "chappal": "640291",
    "chappals": "640291",
    "hawai chappal": "640219",
    "hawaii chappal": "640219",
    "rubber chappal": "640199",
    "rubber slipper": "640199",
    "gents slipper": "640199",
    "ladies slipper": "640199",
    "sports shoe": "640219",
    "canvas shoe": "640411",
    "leather shoe": "640391",
    "leather sandal": "640391",
    "sandal": "640299",
    "sandals": "640299",
    # Dairy
    "milk": "040110",
    "amul milk": "040110",
    "butter": "040510",
    "amul butter": "040510",
    "ghee": "040510",
    "cheese": "040610",
    "paneer": "040610",
    "curd": "040310",
    "yogurt": "040310",
    "dahi": "040310",
    "ice cream": "210500",
    # Staples / Rice / Flour
    "rice": "100630",
    "basmati rice": "100630",
    "raw rice": "100610",
    "wheat flour": "110100",
    "atta": "110100",
    "maida": "110100",
    "besan": "110290",
    "gram flour": "110290",
    "ragi flour": "110290",
    "suji": "110311",
    "semolina": "110311",
    "rava": "110311",
    # Sugar
    "sugar": "170199",
    "jaggery": "170113",
    "gur": "170113",
    # Oils
    "sunflower oil": "151219",
    "palm oil": "151190",
    "coconut oil": "151319",
    "groundnut oil": "151590",
    "mustard oil": "151490",
    "refined oil": "151219",
    "cooking oil": "151219",
    # Beverages
    "water": "220190",
    "mineral water": "220110",
    "cold drink": "220210",
    "cola": "220210",
    "soft drink": "220210",
    "juice": "200990",
    "fruit juice": "200990",
    "tea": "090210",
    "green tea": "090210",
    "coffee": "090111",
    "instant coffee": "210111",
    # Soap / Detergent
    "soap": "340111",
    "bath soap": "340111",
    "toilet soap": "340111",
    "detergent": "340220",
    "washing powder": "340220",
    "surf excel": "340220",
    "ariel": "340220",
    "tide": "340220",
    "vim": "340290",
    "dish wash": "340290",
    # Cosmetics
    "toothpaste": "330610",
    "colgate": "330610",
    "pepsodent": "330610",
    "shampoo": "330510",
    "head and shoulders": "330510",
    "pantene": "330510",
    "dove shampoo": "330510",
    "face cream": "330499",
    "moisturizer": "330499",
    "fairness cream": "330499",
    "deodorant": "330720",
    "perfume": "330300",
    # Medicine
    "paracetamol": "300490",
    "crocin": "300490",
    "dolo": "300490",
    "aspirin": "300490",
    "medicine": "300490",
    "tablet": "300490",
    "capsule": "300490",
    "syrup": "300490",
    "vitamin": "300450",
}

# Retail GST hints where alias resolution should not rely on chapter fallback alone.
_ALIAS_GST_HINTS: dict[str, float] = {
    "640199": 5.0,
    "330741": 12.0,
    "380891": 18.0,
    "340220": 18.0,
    "190531": 18.0,
    "091091": 5.0,
    "091030": 5.0,
    "200990": 12.0,
    "190230": 12.0,
    "170113": 0.0,
}

_OFFICIAL_GST_CACHE: dict[str, float] | None = None


def _build_official_gst_cache() -> dict[str, float]:
    cache: dict[str, float] = {}
    for row in _load_official_rows():
        code = str(row.get("hsn_code") or "")
        gst = row.get("gst_rate")
        if code and gst is not None:
            cache[code] = float(gst)
    return cache


def lookup_tariff_gst(hsn_code: str) -> float | None:
    """Resolve GST from data/hsn_codes.csv (in-memory), then chapter schedule."""
    global _OFFICIAL_GST_CACHE
    if _OFFICIAL_GST_CACHE is None:
        _OFFICIAL_GST_CACHE = _build_official_gst_cache()
    canonical = canonicalize_hsn(hsn_code)
    if not canonical:
        return None
    if canonical in _OFFICIAL_GST_CACHE:
        return _OFFICIAL_GST_CACHE[canonical]
    # Prefer the most specific CSV row sharing the same 6-digit heading.
    head6 = canonical[:6]
    candidates = [
        (code, rate)
        for code, rate in _OFFICIAL_GST_CACHE.items()
        if code.startswith(head6)
    ]
    if candidates:
        candidates.sort(key=lambda item: len(item[0]), reverse=True)
        return candidates[0][1]
    return _chapter_gst_fallback(canonical)


def resolve_alias_gst(hsn_code: str) -> float | None:
    """GST for in-memory alias hits (product-specific hint, then CSV, then chapter)."""
    digits = re.sub(r"[^0-9]", "", hsn_code or "")
    for width in (6, 4):
        if len(digits) >= width:
            hint = _ALIAS_GST_HINTS.get(digits[:width])
            if hint is not None:
                return hint
    return lookup_tariff_gst(digits)


_MIN_BOUNDARY_ALIAS_LEN = 4


def _alias_matches_text(alias: str, text: str) -> bool:
    """Match alias with word boundaries so short tokens (e.g. oil) do not hit coil/foil."""
    if not alias or not text:
        return False
    if text == alias or text.startswith(alias + " "):
        return True
    if len(alias) < _MIN_BOUNDARY_ALIAS_LEN:
        return False
    if alias in text:
        pattern = r"(?:^|\s)" + re.escape(alias) + r"(?:\s|$)"
        return bool(re.search(pattern, text))
    return False


def _alias_match_texts(query: str) -> tuple[str, str]:
    """Build lowercase match strings with punctuation collapsed to spaces."""
    from app.services.normalizer import normalize_product_name

    def _collapse(raw: str) -> str:
        t = re.sub(r"[^a-z0-9\s]", " ", raw.lower())
        return re.sub(r"\s+", " ", t).strip()

    return _collapse(query), _collapse(normalize_product_name(query))


def get_alias_hsn(query: str) -> str | None:
    """Return verified HSN code for a known product query, or None."""
    q, norm = _alias_match_texts(query)
    for candidate in (q, norm):
        if candidate in _VERIFIED_PRODUCT_ALIASES:
            return _VERIFIED_PRODUCT_ALIASES[candidate]
    # Longest alias first so "rubber chappal" beats "chappal"
    for alias, code in sorted(_VERIFIED_PRODUCT_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        for text in (q, norm):
            if _alias_matches_text(alias, text):
                return code
    return None


def _load_official_rows() -> list[dict[str, Any]]:
    if not _DATA_PATH.exists():
        log.warning("hsn_master.official_missing", path=str(_DATA_PATH))
        return []

    deduped: dict[str, dict[str, Any]] = {}
    lines = [
        line
        for line in _DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    reader = csv.DictReader(lines)
    for row in reader:
        raw_code = re.sub(r"[^0-9]", "", str(row.get("hsn_code", "")).strip())
        description = str(row.get("description", "")).strip()
        if not raw_code or not description:
            continue
        # Parse gst_rate from CSV if present
        gst_rate_raw = str(row.get("gst_rate", "")).strip()
        gst_rate: float | None = None
        try:
            gst_rate = float(gst_rate_raw) if gst_rate_raw else None
        except (ValueError, TypeError):
            gst_rate = None
        candidate = {
            "raw_hsn_code": raw_code,
            "hsn_code": canonicalize_hsn(raw_code),
            "description": description,
            "significance": len(raw_code),
            "gst_rate": gst_rate,
        }
        current = deduped.get(raw_code)
        if current is None or len(description) > len(str(current["description"])):
            deduped[raw_code] = candidate
    return list(deduped.values())


def _load_verified_rows() -> list[dict[str, Any]]:
    if not _VERIFIED_DATA_PATH.exists():
        log.warning("hsn_master.verified_missing", path=str(_VERIFIED_DATA_PATH))
        return []

    try:
        raw_rows = _read_xlsx_rows(_VERIFIED_DATA_PATH)
    except Exception as exc:
        log.warning("hsn_master.verified_read_failed", error=str(exc))
        return []

    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        code = row.get("hsn_code", "") or row.get("HSN_SAC", "")
        canonical = canonicalize_hsn(code)
        description = str(row.get("description", "") or row.get("Description", "")).strip()
        if not canonical or not description:
            continue
        raw_code = re.sub(r"[^0-9]", "", str(code or "").strip())
        rows.append(
            {
                "raw_hsn_code": raw_code,
                "hsn_code": canonical,
                "description": description,
                "gst_rate": _clean_gst(row.get("gst_rate", "") or row.get("GST(As Per The GST)", "")),
                "category": None,
                "significance": len(raw_code) if raw_code else 8,
            }
        )
    return rows


def _load_batch_rows() -> list[dict[str, Any]]:
    if not _PRODUCT_BATCH_DIR.exists():
        log.warning("hsn_master.batch_missing", path=str(_PRODUCT_BATCH_DIR))
        return []

    rows: list[dict[str, Any]] = []
    for path in sorted(_PRODUCT_BATCH_DIR.glob("*.json")):
        if path.name == "_index.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("hsn_master.batch_read_failed", file=path.name, error=str(exc))
            continue

        if not isinstance(payload, list):
            continue

        for item in payload:
            raw_code = re.sub(r"[^0-9]", "", str(item.get("HSN_Ref", "")).strip())
            canonical = canonicalize_hsn(raw_code)
            description = str(item.get("Description", "")).strip()
            if not canonical or not description:
                continue
            rows.append(
                {
                    "raw_hsn_code": raw_code,
                    "hsn_code": canonical,
                    "description": description,
                    "gst_rate": _clean_gst(item.get("GST_Ref", "")),
                    "category": _normalise_category(item.get("Category_L2", "")),
                    "significance": len(raw_code) if raw_code else 8,
                }
            )
    return rows


def _pick_duplicate_official_description(descriptions: list[str], gst_rate: float | None) -> str:
    if len(descriptions) == 1:
        return descriptions[0]

    default = descriptions[0]
    if gst_rate is None or gst_rate <= 0 or gst_rate > 5:
        return default

    for description in descriptions:
        lower = description.lower()
        if "commercial use" in lower:
            continue
        if any(token in lower for token in _GST_QUALIFIER_TOKENS):
            return description

    return default


def _majority_gst_rate(votes: Counter[float]) -> float | None:
    if not votes:
        return None
    most_common_rate, count = votes.most_common(1)[0]
    if count >= 2 or len(votes) == 1:
        return most_common_rate
    return None


def build_hsn_master_records(
    *,
    official_rows: list[dict[str, Any]] | None = None,
    verified_rows: list[dict[str, Any]] | None = None,
    batch_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    official_rows = _load_official_rows() if official_rows is None else official_rows
    verified_rows = _load_verified_rows() if verified_rows is None else verified_rows
    batch_rows = _load_batch_rows() if batch_rows is None else batch_rows

    official_by_prefix: dict[str, list[str]] = defaultdict(list)
    official_gst_by_code: dict[str, float] = {}
    significance_by_code: dict[str, int] = defaultdict(int)

    for row in official_rows:
        raw_code = re.sub(r"[^0-9]", "", str(row.get("raw_hsn_code", row.get("hsn_code", ""))).strip())
        canonical = canonicalize_hsn(raw_code or row.get("hsn_code", ""))
        description = str(row.get("description", "")).strip()
        if not raw_code or not canonical or not description:
            continue
        official_by_prefix[raw_code].append(description)
        significance_by_code[canonical] = max(significance_by_code[canonical], len(raw_code))
        if row.get("gst_rate") is not None:
            official_gst_by_code[canonical] = float(row["gst_rate"])

    evidence_rows = []
    evidence_rows.extend(verified_rows)
    evidence_rows.extend(batch_rows)

    gst_votes: dict[str, Counter[float]] = defaultdict(Counter)
    for row in evidence_rows:
        canonical = canonicalize_hsn(row.get("hsn_code", ""))
        if not canonical:
            continue
        raw_code = re.sub(r"[^0-9]", "", str(row.get("raw_hsn_code", row.get("hsn_code", ""))).strip())
        significance_by_code[canonical] = max(
            significance_by_code[canonical],
            len(raw_code) if raw_code else 8,
        )
        gst_rate = row.get("gst_rate")
        if gst_rate is not None:
            gst_votes[canonical][float(gst_rate)] += 1

    all_codes = set(significance_by_code)
    all_codes.update(canonicalize_hsn(row.get("hsn_code", "")) for row in evidence_rows)
    all_codes.update(canonicalize_hsn(row.get("hsn_code", "")) for row in official_rows)
    all_codes.discard("")

    records: list[dict[str, Any]] = []
    for code in sorted(all_codes):
        significance = significance_by_code.get(code, 8)
        _voted_gst = _majority_gst_rate(gst_votes[code]) if gst_votes.get(code) else None
        gst_rate = official_gst_by_code.get(code)
        if gst_rate is None:
            gst_rate = _voted_gst if _voted_gst is not None else _chapter_gst_fallback(code)

        official_candidates: list[tuple[int, str]] = []
        for length in (8, 6, 4, 2):
            if length > significance:
                continue
            prefix = code[:length]
            descriptions = official_by_prefix.get(prefix, [])
            if not descriptions:
                continue
            official_candidates.append(
                (length, _pick_duplicate_official_description(descriptions, gst_rate))
            )

        official_candidates.sort(key=lambda item: item[0], reverse=True)
        cbic_description = official_candidates[0][1] if official_candidates else None

        parent_heading_desc = None
        heading_descriptions = official_by_prefix.get(code[:4], [])
        if significance > 4 and heading_descriptions:
            parent_heading_desc = _pick_duplicate_official_description(heading_descriptions, gst_rate)

        records.append(
            {
                "hsn_code": code,
                "hsn_chapter": code[:2],
                "hsn_heading": code[:4],
                "hsn_subheading": code[:6],
                "description": cbic_description or parent_heading_desc or "HSN description unavailable",
                "cbic_description": cbic_description,
                "parent_heading_desc": parent_heading_desc,
                "gst_rate": gst_rate,
                "category": None,
                "schedule": None,
                "source": "CSV_ENRICHED",
                "is_active": True,
            }
        )

    log.info(
        "hsn_master.records_built",
        total=len(records),
        official_rows=len(official_rows),
        verified_rows=len(verified_rows),
        batch_rows=len(batch_rows),
    )
    return records
