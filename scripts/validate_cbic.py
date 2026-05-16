#!/usr/bin/env python3
"""Validate hsn_codes.csv against CBIC/GST data integrity rules for CI."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

VALID_GST_SLABS = {0, 0.1, 0.25, 1.5, 3, 5, 12, 18, 28}
CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "hsn_codes.csv"


def _parse_gst(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    return float(text)


def _is_valid_sac(code: str) -> bool:
    """SAC service codes are 8-digit codes starting with 99."""
    return len(code) == 8 and code.isdigit() and code.startswith("99")


def validate(csv_path: Path = CSV_PATH) -> int:
    if not csv_path.is_file():
        print(f"ERROR: {csv_path} not found")
        return 1

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    invalid_codes: list[str] = []
    sac_violations: list[str] = []
    gst_anomalies: list[str] = []

    for row in rows:
        code = (row.get("hsn_code") or "").strip()
        if len(code) != 8 or not code.isdigit():
            invalid_codes.append(code or "<empty>")

        if code.startswith("99") and not _is_valid_sac(code):
            sac_violations.append(code)

        gst = _parse_gst(row.get("gst_rate", ""))
        if gst is not None and gst not in VALID_GST_SLABS:
            gst_anomalies.append(f"{code}: gst_rate={gst}")

    total = len(rows)
    print(f"CBIC HSN validation report — {csv_path.name}")
    print(f"  Total codes:        {total}")
    print(f"  Invalid code format:{len(invalid_codes)}")
    print(f"  SAC (99*) violations:{len(sac_violations)}")
    print(f"  GST rate anomalies: {len(gst_anomalies)}")

    if invalid_codes:
        print("\nInvalid codes (must be exactly 8 digits):")
        for c in invalid_codes[:50]:
            print(f"  - {c}")
        if len(invalid_codes) > 50:
            print(f"  ... and {len(invalid_codes) - 50} more")

    if sac_violations:
        print("\nCodes starting with 99 that are not valid 8-digit SAC:")
        for c in sac_violations[:50]:
            print(f"  - {c}")

    if gst_anomalies:
        print("\nGST rate anomalies:")
        for line in gst_anomalies[:50]:
            print(f"  - {line}")

    has_errors = bool(invalid_codes or sac_violations or gst_anomalies)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(validate())
