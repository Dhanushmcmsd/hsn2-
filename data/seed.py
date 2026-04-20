#!/usr/bin/env python3
"""
data/seed_verified.py  —  v2
============================
Seeds (or re-seeds) the verified_products table from correct_datas.xlsx.

correct_datas.xlsx column layout:
  Col 0  →  Description                   (raw POS/billing product text)
  Col 1  →  HSN_SAC (As per The GST)      (8-digit HSN code, ground-truth)
  Col 2  →  GST(As Per The GST)           (e.g. "GST 18%")

Two normalised forms are stored per row:
  description_normalized   exact UPPERCASE (unique key, Pass-0A lookup)
  description_no_size      size tokens stripped (Pass-0B fallback lookup)

Usage
-----
  DATABASE_URL="postgresql://..." python data/seed_verified.py
  DATABASE_URL="postgresql://..." python data/seed_verified.py --truncate
  DATABASE_URL="postgresql://..." python data/seed_verified.py --dry-run
  DATABASE_URL="postgresql://..." python data/seed_verified.py --xlsx path/to/other.xlsx
"""
import argparse
import os
import re
import sys

import pandas as pd
from sqlalchemy import create_engine, text

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Seed verified_products from correct_datas.xlsx")
parser.add_argument("--xlsx", default=os.path.join(os.path.dirname(__file__), "correct_datas.xlsx"),
                    help="Path to correct_datas.xlsx")
parser.add_argument("--sheet", default=0, help="Sheet name or 0-based index (default: 0)")
parser.add_argument("--dry-run", action="store_true", help="Parse and validate only — no DB write")
parser.add_argument("--truncate", action="store_true", help="Truncate table before seeding")
args = parser.parse_args()

# ── DB connection ─────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL environment variable is not set.")

DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# ── Normalisation helpers ─────────────────────────────────────────────────────

_SIZE_PAT = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|'
    r'PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB)\b'
    r'|\b\d+\s*X\s*\d+\b'
    r'|\b\d+\s*\+\s*\d+\b'
    r'|\b\d+S\b|\b\d+N\b|\b\d+P\b'
    r'|\b\d+\b',
    re.IGNORECASE,
)


def strip_sizes(text: str) -> str:
    """Remove weight/volume/count tokens; return UPPERCASE cleaned string."""
    t = _SIZE_PAT.sub(' ', text.upper())
    t = re.sub(r'[^A-Z\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def clean_hsn(raw) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    digits = re.sub(r'[^0-9]', '', str(raw).strip())
    if not digits:
        return None
    return digits.zfill(8)


def clean_gst(raw) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    m = re.search(r'(\d+)', str(raw))
    return m.group(1) + '%' if m else None


# ── Load Excel ────────────────────────────────────────────────────────────────
if not os.path.exists(args.xlsx):
    sys.exit(f"ERROR: File not found: {args.xlsx}")

print(f"📖  Reading {args.xlsx} …")
try:
    sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
    df = pd.read_excel(args.xlsx, sheet_name=sheet, header=0)
except Exception as e:
    sys.exit(f"ERROR reading Excel: {e}")

cols = df.columns.tolist()
print(f"    Columns detected ({len(cols)}): {cols}")
print(f"    Rows: {len(df):,}")


def _find_col(candidates: list[str], position: int) -> str | None:
    """Case-insensitive name search, then positional fallback."""
    cols_lower = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return cols[position] if position < len(cols) else None


desc_col = _find_col(
    ["description", "product description", "product name", "item name", "item"], 0
)
hsn_col = _find_col(
    ["hsn_sac (as per the gst)", "hsn_sac", "hsn as per gst",
     "hsn_as_per_gst", "hsn code", "hsn"], 1
)
gst_col = _find_col(
    ["gst(as per the gst)", "gst as per the gst", "gst as per gst",
     "gst_as_per_gst", "gst rate", "gst"], 2
)

if not desc_col:
    sys.exit(f"ERROR: Cannot find description column. Available: {cols}")
if not hsn_col:
    sys.exit(f"ERROR: Cannot find HSN code column. Available: {cols}")

print(f"\n    Column mapping:")
print(f"      Description → '{desc_col}'  (col {cols.index(desc_col)})")
print(f"      HSN code    → '{hsn_col}'   (col {cols.index(hsn_col)})")
print(f"      GST rate    → '{gst_col}'   (col {cols.index(gst_col) if gst_col else 'N/A'})")


# ── Build records ─────────────────────────────────────────────────────────────
records = []
seen_exact: set[str] = set()
skipped = 0

for _, row in df.iterrows():
    raw_desc = row.get(desc_col)
    raw_hsn  = row.get(hsn_col)
    raw_gst  = row.get(gst_col) if gst_col else None

    desc = str(raw_desc).strip() if raw_desc and str(raw_desc) != 'nan' else ""
    hsn  = clean_hsn(raw_hsn)
    gst  = clean_gst(raw_gst)

    if not desc or not hsn:
        skipped += 1
        continue

    desc_norm    = desc.upper().strip()
    desc_no_size = strip_sizes(desc)

    if desc_norm in seen_exact:
        skipped += 1
        continue
    seen_exact.add(desc_norm)

    records.append({
        "description":          desc,
        "description_normalized": desc_norm,
        "description_no_size":  desc_no_size,
        "hsn_code":             hsn,
        "gst_rate":             gst,
    })

print(f"\n    Valid records  : {len(records):,}")
print(f"    Skipped        : {skipped:,}")

if args.dry_run:
    print("\n✅  Dry run — no changes written.")
    print("\nSample (first 10):")
    for r in records[:10]:
        print(f"  {r['description'][:45]:<45} | {r['hsn_code']} | {r['gst_rate']} | no_size='{r['description_no_size'][:35]}'")
    sys.exit(0)


# ── Ensure schema has description_no_size column ──────────────────────────────
with engine.begin() as conn:
    # Add column if it doesn't exist (idempotent)
    conn.execute(text("""
        ALTER TABLE verified_products
        ADD COLUMN IF NOT EXISTS description_no_size VARCHAR(500)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_verified_no_size
        ON verified_products (description_no_size)
    """))


# ── Write to DB ───────────────────────────────────────────────────────────────
print(f"\n⬆️   Writing {len(records):,} records to verified_products …")

upsert_sql = text("""
    INSERT INTO verified_products
        (description, description_normalized, description_no_size, hsn_code, gst_rate)
    VALUES
        (:description, :description_normalized, :description_no_size, :hsn_code, :gst_rate)
    ON CONFLICT (description_normalized) DO UPDATE SET
        description_no_size = EXCLUDED.description_no_size,
        hsn_code            = EXCLUDED.hsn_code,
        gst_rate            = EXCLUDED.gst_rate
""")

BATCH = 500
inserted = 0

with engine.begin() as conn:
    if args.truncate:
        conn.execute(text("TRUNCATE TABLE verified_products RESTART IDENTITY"))
        print("    Truncated existing records.")

    for i in range(0, len(records), BATCH):
        batch = records[i : i + BATCH]
        conn.execute(upsert_sql, batch)
        inserted += len(batch)
        print(f"    {inserted:,} / {len(records):,} …", end="\r")

print(f"\n✅  Done — {inserted:,} records upserted into verified_products.")
print("\nVerify:")
print("  psql $DATABASE_URL -c \"SELECT COUNT(*) FROM verified_products;\"")
print("  psql $DATABASE_URL -c \"SELECT description, hsn_code, gst_rate")
print("    FROM verified_products WHERE description_normalized = 'TATA SALT IODISED 1KG';\"")
