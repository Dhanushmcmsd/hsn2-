from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import structlog

from app.services.hsn_master import build_hsn_master_records

log = structlog.get_logger()

_DATASET: list[dict] = []
_VERSION = "v2.0"

_DATA_PATH = Path(os.getenv("HSN_DATA_PATH", "data/hsn_codes.csv"))
_VERIFIED_DATA_PATH = Path(os.getenv("VERIFIED_DATA_PATH", "data/correct_datas.xlsx"))
_PRODUCT_BATCH_DIR = Path(os.getenv("PRODUCT_BATCH_DIR", "data/product_batches"))

_XL_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _normalize_text(text: str) -> str:
    text = str(text or "").upper()
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_sizes(text: str) -> str:
    text = _normalize_text(text)
    text = re.sub(
        r"\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|"
        r"PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB)\b",
        " ",
        text,
    )
    text = re.sub(r"\b\d+\s*X\s*\d+\b", " ", text)
    text = re.sub(r"\b\d+\s*\+\s*\d+\b", " ", text)
    text = re.sub(r"\b\d+[SNP]\b", " ", text)
    text = re.sub(r"\b\d+\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_hsn(raw: object) -> str:
    digits = re.sub(r"[^0-9]", "", str(raw or "").strip())
    return digits.zfill(8) if digits else ""


def _clean_gst(raw: object) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)", str(raw or ""))
    return match.group(1) if match else ""


def _build_record(
    *,
    hsn_code: str,
    description: str,
    source: str,
    gst_rate: str = "",
    category: str = "",
) -> dict | None:
    cleaned_hsn = _clean_hsn(hsn_code)
    cleaned_description = str(description or "").strip()
    if not cleaned_hsn or not cleaned_description:
        return None
    description_normalized = _normalize_text(cleaned_description)
    description_no_size = _strip_sizes(cleaned_description)
    return {
        "hsn_code": cleaned_hsn,
        "description": cleaned_description,
        "source": source,
        "gst_rate": gst_rate,
        "category": category,
        "description_normalized": description_normalized,
        "description_no_size": description_no_size,
    }


def _load_hsn_codes() -> list[dict]:
    rows: list[dict] = []
    for row in build_hsn_master_records():
        gst_rate = row.get("gst_rate")
        record = _build_record(
            hsn_code=row.get("hsn_code", ""),
            description=row.get("description", ""),
            source="hsn_codes",
            gst_rate="" if gst_rate is None else str(gst_rate).rstrip("0").rstrip("."),
            category=row.get("category", "") or "",
        )
        if record:
            rows.append(record)
    return rows


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


def _load_verified_rows() -> list[dict]:
    if not _VERIFIED_DATA_PATH.exists():
        log.warning("dataset.verified_missing", path=str(_VERIFIED_DATA_PATH))
        return []

    try:
        raw_rows = _read_xlsx_rows(_VERIFIED_DATA_PATH)
    except Exception as exc:
        log.warning("dataset.verified_read_failed", error=str(exc))
        return []

    rows: list[dict] = []
    for row in raw_rows:
        record = _build_record(
            hsn_code=row.get("hsn_code", "") or row.get("HSN_SAC", ""),
            description=row.get("description", "") or row.get("Description", ""),
            source="correct_datas",
            gst_rate=_clean_gst(row.get("gst_rate", "") or row.get("GST(As Per The GST)", "")),
        )
        if record:
            rows.append(record)
    return rows


def _load_product_batch_rows() -> list[dict]:
    if not _PRODUCT_BATCH_DIR.exists():
        log.warning("dataset.product_batches_missing", path=str(_PRODUCT_BATCH_DIR))
        return []

    rows: list[dict] = []
    for path in sorted(_PRODUCT_BATCH_DIR.glob("*.json")):
        if path.name == "_index.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("dataset.batch_read_failed", file=path.name, error=str(exc))
            continue

        if not isinstance(payload, list):
            continue

        for item in payload:
            record = _build_record(
                hsn_code=item.get("HSN_Ref", ""),
                description=item.get("Description", ""),
                source="product_batch",
                gst_rate=_clean_gst(item.get("GST_Ref", "")),
                category=str(item.get("Category_L2", "")).strip(),
            )
            if record:
                rows.append(record)
    return rows


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    source_rank = {"correct_datas": 3, "product_batch": 2, "hsn_codes": 1}

    for row in rows:
        key = (row["hsn_code"], row["description_normalized"])
        existing = grouped.get(key)
        if not existing:
            grouped[key] = dict(row)
            continue

        if source_rank.get(row["source"], 0) > source_rank.get(existing["source"], 0):
            merged = dict(existing)
            merged.update(row)
            grouped[key] = merged
            existing = grouped[key]

        if not existing.get("gst_rate") and row.get("gst_rate"):
            existing["gst_rate"] = row["gst_rate"]
        if not existing.get("category") and row.get("category"):
            existing["category"] = row["category"]

    return list(grouped.values())


def _attach_aliases(rows: list[dict]) -> list[dict]:
    by_hsn: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_hsn[row["hsn_code"]].append(row)

    output: list[dict] = []
    for row in rows:
        related = by_hsn[row["hsn_code"]]
        aliases = sorted(
            {
                item["description_normalized"]
                for item in related
                if item["description_normalized"] != row["description_normalized"]
            }
        )[:12]
        row_copy = dict(row)
        row_copy["aliases"] = aliases
        output.append(row_copy)
    return output


def load_dataset() -> list[dict]:
    global _DATASET, _VERSION

    rows = []
    rows.extend(_load_hsn_codes())
    rows.extend(_load_verified_rows())
    rows.extend(_load_product_batch_rows())

    deduped = _attach_aliases(_dedupe_rows(rows))
    _DATASET = deduped

    checksum_input = [
        (row["hsn_code"], row["description_normalized"], row["source"])
        for row in _DATASET
    ]
    checksum = hashlib.md5(str(checksum_input).encode(), usedforsecurity=False).hexdigest()[:10]
    counts = defaultdict(int)
    for row in _DATASET:
        counts[row["source"]] += 1
    _VERSION = (
        f"v2.0-{checksum}"
        f"-master{counts['hsn_codes']}"
        f"-verified{counts['correct_datas']}"
        f"-batch{counts['product_batch']}"
    )
    log.info("dataset.loaded", count=len(_DATASET), version=_VERSION, sources=dict(counts))
    return _DATASET


def get_dataset() -> list[dict]:
    if not _DATASET:
        load_dataset()
    return _DATASET


def get_dataset_version() -> str:
    return _VERSION
