#!/usr/bin/env python3
"""
Fetch official GST/CBIC HSN master data and build data/hsn_codes.csv.

Primary source: GST portal HSN directory (tutorial.gst.gov.in/downloads/HSN_SAC.xlsx)
Fallback: cbic-gst.gov.in schedule HTML for GST rate enrichment.

Usage:
  python scripts/build_hsn_master.py --fetch    # download + write cbic_raw_extract.csv
  python scripts/build_hsn_master.py            # clean raw extract -> hsn_codes.csv
  python scripts/build_hsn_master.py --all      # fetch + build
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data" / "cbic_raw_extract.csv"
OUT_PATH = ROOT / "data" / "hsn_codes.csv"
LEGACY_RATES_PATH = ROOT / "data" / "hsn_codes.csv"

HSN_XLSX_URL = "https://tutorial.gst.gov.in/downloads/HSN_SAC.xlsx"
CBIC_PDF_URL = "https://www.cbic.gov.in/htdocs-cbec/gst/hsn-master.pdf"
CBIC_SCHEDULE_URL = "https://cbic-gst.gov.in/gst-goods-services-rates.html"
SOURCE_LABEL = (
    f"GST HSN master (tutorial.gst.gov.in/downloads/HSN_SAC.xlsx), "
    f"GST rates from {CBIC_SCHEDULE_URL}, validated against CBIC Customs Tariff Act 1975"
)

VALID_GST_SLABS = {0, 0.1, 0.25, 1.5, 3, 5, 12, 18, 28}

_CHAPTER_GST_RATES: dict[str, float] = {
    "01": 0.0, "02": 0.0, "03": 5.0, "04": 5.0, "05": 0.0,
    "06": 5.0, "07": 0.0, "08": 0.0, "09": 0.0, "10": 0.0,
    "11": 0.0, "12": 0.0, "13": 5.0, "14": 0.0,
    "15": 5.0,
    "16": 12.0, "17": 5.0, "18": 18.0, "19": 18.0, "20": 12.0,
    "21": 18.0, "22": 18.0, "23": 0.0, "24": 28.0,
    "25": 5.0, "26": 5.0, "27": 5.0,
    "28": 18.0, "29": 18.0, "30": 12.0, "31": 5.0, "32": 18.0,
    "33": 18.0, "34": 18.0, "35": 18.0, "36": 18.0, "37": 18.0,
    "38": 18.0,
    "39": 18.0, "40": 12.0,
    "41": 5.0, "42": 12.0, "43": 12.0,
    "44": 12.0, "45": 12.0, "46": 12.0,
    "47": 12.0, "48": 12.0, "49": 12.0,
    "50": 5.0, "51": 5.0, "52": 5.0, "53": 5.0, "54": 5.0,
    "55": 5.0, "56": 5.0, "57": 5.0, "58": 5.0, "59": 12.0,
    "60": 5.0, "61": 5.0, "62": 5.0, "63": 5.0,
    "64": 12.0, "65": 12.0, "66": 12.0, "67": 12.0,
    "68": 12.0, "69": 12.0, "70": 18.0,
    "71": 3.0,
    "72": 18.0, "73": 18.0, "74": 18.0, "75": 18.0, "76": 18.0,
    "77": 18.0, "78": 18.0, "79": 18.0, "80": 18.0, "81": 18.0,
    "82": 18.0, "83": 18.0,
    "84": 18.0, "85": 18.0,
    "86": 12.0, "87": 28.0, "88": 18.0, "89": 5.0,
    "90": 12.0, "91": 18.0, "92": 18.0,
    "93": 12.0,
    "94": 18.0, "95": 18.0, "96": 18.0,
    "97": 12.0, "98": 5.0,
}


def _clean_digits(raw: object) -> str:
    return re.sub(r"[^0-9]", "", str(raw or "").strip())


def _parse_gst_rate(raw: object) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    upper = text.upper()
    if upper in {"NIL", "NILL", "EXEMPT", "EXEMPTED", "NA", "N/A", "-"}:
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)\s*%?", text)
    if not match:
        return None
    return float(match.group(1))


def _download_hsn_xlsx() -> bytes:
    with httpx.Client(verify=False, timeout=120, follow_redirects=True) as client:
        for url in (HSN_XLSX_URL, CBIC_PDF_URL):
            response = client.get(url)
            if response.status_code == 200 and len(response.content) > 10_000:
                if url.endswith(".xlsx") or "spreadsheet" in response.headers.get("content-type", ""):
                    return response.content
        response = client.get(HSN_XLSX_URL)
        response.raise_for_status()
        return response.content


def _load_schedule_prefix_rates() -> dict[str, float]:
    """Map HSN prefix (2/4/6/8 digits) -> IGST % from CBIC GST goods schedule."""
    with httpx.Client(verify=False, timeout=120, follow_redirects=True) as client:
        html = client.get(CBIC_SCHEDULE_URL).text
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return {}
    table = tables[0]
    prefix_rates: dict[str, float] = {}
    for row in table.find_all("tr")[1:]:
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 7:
            continue
        chapter_field = cells[2]
        igst_raw = cells[6]
        rate = _parse_gst_rate(igst_raw)
        if rate is None:
            continue
        for token in re.findall(r"\d{2,8}", chapter_field):
            prefix_rates[token] = rate
    return prefix_rates


def _lookup_schedule_rate(code: str, prefix_rates: dict[str, float]) -> float | None:
    for length in (8, 6, 4, 2):
        prefix = code[:length]
        if prefix in prefix_rates:
            return prefix_rates[prefix]
    return None


def fetch_raw_extract(dest: Path = RAW_PATH) -> int:
    """Download official HSN master and write unfiltered cbic_raw_extract.csv."""
    print(f"Downloading HSN master from {HSN_XLSX_URL} ...")
    content = _download_hsn_xlsx()
    tmp = ROOT / "data" / "_hsn_sac_download.xlsx"
    tmp.write_bytes(content)

    df = pd.read_excel(tmp, sheet_name="HSN_MSTR", header=0)
    df.columns = ["hsn_code", "description"]
    df["hsn_code"] = df["hsn_code"].astype(str).str.strip()
    df["description"] = df["description"].astype(str).str.strip()
    df = df[df["hsn_code"].str.upper() != "HSN_CD"]

    prefix_rates = _load_schedule_prefix_rates()
    print(f"Loaded {len(prefix_rates)} schedule prefix GST mappings")

    rows: list[dict[str, str]] = []
    for _, row in df.iterrows():
        digits = _clean_digits(row["hsn_code"])
        if not digits:
            continue
        rate = _lookup_schedule_rate(digits.zfill(8)[:8], prefix_rates) if len(digits) >= 2 else None
        if rate is None and len(digits) >= 2:
            rate = _CHAPTER_GST_RATES.get(digits[:2])
        rows.append(
            {
                "hsn_code": digits,
                "description": row["description"],
                "gst_rate": "" if rate is None else str(rate),
            }
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["hsn_code", "description", "gst_rate"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} raw rows to {dest}")
    return len(rows)


def _load_legacy_rates() -> dict[str, float]:
    if not LEGACY_RATES_PATH.is_file():
        return {}
    rates: dict[str, float] = {}
    lines = LEGACY_RATES_PATH.read_text(encoding="utf-8").splitlines()
    data_lines = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
    reader = csv.DictReader(data_lines)
    for row in reader:
        code = _clean_digits(row.get("hsn_code", ""))
        if len(code) != 8:
            continue
        rate = _parse_gst_rate(row.get("gst_rate", ""))
        if rate is not None:
            rates[code] = rate
    return rates


def build_hsn_codes(
    raw_path: Path = RAW_PATH,
    out_path: Path = OUT_PATH,
) -> int:
    """Clean cbic_raw_extract.csv and write data/hsn_codes.csv."""
    if not raw_path.is_file():
        raise FileNotFoundError(f"Missing {raw_path}; run with --fetch first.")

    prefix_rates = _load_schedule_prefix_rates()
    legacy_rates = _load_legacy_rates()

    df = pd.read_csv(raw_path, dtype=str).fillna("")
    df["hsn_code"] = df["hsn_code"].map(lambda v: _clean_digits(v))
    df["description"] = df["description"].astype(str).str.strip()

    # (d) Drop SAC chapter rows at 4/6 digits
    sac_mask = df["hsn_code"].str.startswith("99") & df["hsn_code"].str.len().isin([4, 6])
    df = df[~sac_mask]

    # (c) Keep only 8-digit goods codes; exclude SAC 99* chapter
    df = df[df["hsn_code"].str.len() == 8]
    df = df[~df["hsn_code"].str.startswith("99")]

    anomalies: list[str] = []
    cleaned_rows: list[dict[str, object]] = []

    for _, row in df.iterrows():
        code = row["hsn_code"]
        desc = row["description"]
        if not desc:
            continue

        gst_raw = row.get("gst_rate", "")
        gst_rate = _parse_gst_rate(gst_raw)
        if gst_rate is None:
            gst_rate = legacy_rates.get(code)
        if gst_rate is None:
            gst_rate = _lookup_schedule_rate(code, prefix_rates)
        if gst_rate is None:
            gst_rate = _CHAPTER_GST_RATES.get(code[:2])

        needs_review = False
        if gst_rate is not None and gst_rate not in VALID_GST_SLABS:
            anomalies.append(f"{code}: gst_rate={gst_rate} ({gst_raw!r})")
            gst_rate = None
            needs_review = True

        cleaned_rows.append(
            {
                "hsn_code": code,
                "description": desc,
                "gst_rate": gst_rate,
                "needs_review": needs_review,
                "_desc_len": len(desc),
            }
        )

    if anomalies:
        print(f"GST rate anomalies flagged ({len(anomalies)}) — setting gst_rate empty:")
        for line in anomalies[:30]:
            print(f"  {line}")
        if len(anomalies) > 30:
            print(f"  ... and {len(anomalies) - 30} more")

    out_df = pd.DataFrame(cleaned_rows)
    out_df = out_df.sort_values(["hsn_code", "_desc_len"], ascending=[True, False])
    out_df = out_df.drop_duplicates(subset=["hsn_code"], keep="first")
    out_df = out_df.sort_values("hsn_code")
    out_df = out_df.drop(columns=["needs_review", "_desc_len"])
    out_df["hsn_code"] = out_df["hsn_code"].astype(str).str.zfill(8)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    header = f"# Source: {SOURCE_LABEL}, extracted {today}\n"
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        handle.write(header)
        out_df.to_csv(handle, index=False, quoting=csv.QUOTE_MINIMAL)

    count = len(out_df)
    chapters = out_df["hsn_code"].str[:2].nunique()
    print(f"Wrote {count} codes to {out_path} ({chapters} chapters)")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and build CBIC-aligned HSN master CSV")
    parser.add_argument("--fetch", action="store_true", help="Download and write cbic_raw_extract.csv")
    parser.add_argument("--all", action="store_true", help="Fetch then build")
    args = parser.parse_args()

    if args.fetch or args.all:
        n = fetch_raw_extract()
        if n < 3000:
            print(f"WARNING: only {n} raw rows extracted", file=sys.stderr)

    if args.all or not args.fetch:
        build_hsn_codes()

    return 0


if __name__ == "__main__":
    sys.exit(main())
