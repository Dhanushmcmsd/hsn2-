from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


VALID_RATES = {0, 5, 12, 18, 28}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {
        "hsn": "hsn_code",
        "hsn_code": "hsn_code",
        "description": "description",
        "gst_rate": "gst_rate",
        "rate": "gst_rate",
        "chapter": "chapter",
        "section": "section",
        "unit_of_measurement": "unit_of_measurement",
        "uom": "unit_of_measurement",
        "effective_from": "effective_from",
    }
    out = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in mapping:
            out[mapping[key]] = df[col]
    norm = pd.DataFrame(out)
    for col in ["hsn_code", "description", "gst_rate", "chapter", "section", "unit_of_measurement", "effective_from"]:
        if col not in norm.columns:
            norm[col] = None
    return norm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=str)
    args = parser.parse_args()
    root = Path(args.folder)
    frames = []
    for path in sorted(root.glob("*")):
        if path.suffix.lower() == ".csv":
            frames.append(normalize_columns(pd.read_csv(path)))
        elif path.suffix.lower() in {".xlsx", ".xls"}:
            frames.append(normalize_columns(pd.read_excel(path)))
    if not frames:
        raise SystemExit("No input files found")
    df = pd.concat(frames, ignore_index=True)
    df["hsn_code"] = df["hsn_code"].astype(str).str.replace(r"[^0-9]", "", regex=True)
    df = df[df["hsn_code"].str.match(r"^[0-9]{2,8}$", na=False)]
    df["description"] = df["description"].astype(str).str.strip()
    df = df[df["description"] != ""]
    df["gst_rate"] = pd.to_numeric(df["gst_rate"], errors="coerce")
    df = df[df["gst_rate"].isin(VALID_RATES)]
    df["effective_from"] = pd.to_datetime(df["effective_from"], errors="coerce")
    before = len(df)
    df = df.sort_values("effective_from").drop_duplicates(subset=["hsn_code"], keep="last")
    removed = before - len(df)
    out_path = Path("data/hsn_codes_full.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if Path("data/hsn_codes.csv").exists() and not Path("data/hsn_codes_v1_34rows.csv").exists():
        Path("data/hsn_codes.csv").rename("data/hsn_codes_v1_34rows.csv")
    df.to_csv(out_path, index=False)
    counts = df["gst_rate"].value_counts().to_dict()
    print(f"total rows: {len(df)}")
    print(f"rows per GST tier: {counts}")
    print(f"duplicates removed: {removed}")


if __name__ == "__main__":
    main()
