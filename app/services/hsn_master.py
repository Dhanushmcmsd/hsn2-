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


def _load_official_rows() -> list[dict[str, Any]]:
    if not _DATA_PATH.exists():
        log.warning("hsn_master.official_missing", path=str(_DATA_PATH))
        return []

    rows: list[dict[str, Any]] = []
    with _DATA_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_code = re.sub(r"[^0-9]", "", str(row.get("hsn_code", "")).strip())
            description = str(row.get("description", "")).strip()
            if not raw_code or not description:
                continue
            rows.append(
                {
                    "raw_hsn_code": raw_code,
                    "hsn_code": canonicalize_hsn(raw_code),
                    "description": description,
                    "significance": len(raw_code),
                }
            )
    return rows


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
    significance_by_code: dict[str, int] = defaultdict(int)

    for row in official_rows:
        raw_code = re.sub(r"[^0-9]", "", str(row.get("raw_hsn_code", row.get("hsn_code", ""))).strip())
        canonical = canonicalize_hsn(raw_code or row.get("hsn_code", ""))
        description = str(row.get("description", "")).strip()
        if not raw_code or not canonical or not description:
            continue
        official_by_prefix[raw_code].append(description)
        significance_by_code[canonical] = max(significance_by_code[canonical], len(raw_code))

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
        gst_rate = gst_votes[code].most_common(1)[0][0] if gst_votes.get(code) else None

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
