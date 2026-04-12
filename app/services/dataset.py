from __future__ import annotations
import csv
import os
import hashlib
from pathlib import Path
import structlog

log = structlog.get_logger()
_DATASET: list[dict] = []
_VERSION = "v1.0"
_DATA_PATH = Path(os.getenv("HSN_DATA_PATH", "data/hsn_codes.csv"))


def load_dataset() -> list[dict]:
    global _DATASET, _VERSION
    if not _DATA_PATH.exists():
        log.warning("dataset.file_missing", path=str(_DATA_PATH))
        return _DATASET
    rows = []
    with open(_DATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "hsn_code": row.get("hsn_code", "").strip(),
                "description": row.get("description", "").strip(),
            })
    _DATASET = [r for r in rows if r["hsn_code"] and r["description"]]
    checksum = hashlib.md5(str(_DATASET).encode()).hexdigest()[:8]
    _VERSION = f"v1.0-{checksum}"
    log.info("dataset.loaded", count=len(_DATASET), version=_VERSION)
    return _DATASET


def get_dataset() -> list[dict]:
    if not _DATASET:
        load_dataset()
    return _DATASET


def get_dataset_version() -> str:
    return _VERSION
