"""
Seed the Neon PostgreSQL database with HSN/GST master data.
Run once:  DATABASE_URL="postgresql://..." python data/seed.py

Requires:  pip install pandas openpyxl sqlalchemy psycopg2-binary
"""
import os, sys#!/usr/bin/env python3
"""
data/seed_verified.py
=====================
Seeds the verified_products table from correct_datas.xlsx.

Column mapping in correct_datas.xlsx (0-indexed):
  Col 0 = Product description (raw POS/billing text)
  Col 4 = HSN As per GST  ← authoritative HSN code
  Col 5 = GST As Per GST  ← authoritative GST rate

Usage:
  DATABASE_URL="postgresql://..." python data/seed_verified.py
  DATABASE_URL="postgresql://..." python data/seed_verified.py --xlsx data/correct_datas.xlsx
  DATABASE_URL="postgresql://..." python data/seed_verified.py --dry-run

Requirements:
  pip install pandas openpyxl psycopg2-binary sqlalchemy
"""

import os
import sys
import re
import argparse
import pandas as pd
from sqlalchemy import create_engine, text

# ── CLI args ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Seed verified_products from correct_datas.xlsx")
parser.add_argument(
    "--xlsx",
    default=os.path.join(os.path.dirname(__file__), "correct_datas.xlsx"),
    help="Path to correct_datas.xlsx (default: data/correct_datas.xlsx)",
)
parser.add_argument(
    "--sheet",
    default=0,
    help="Sheet name or 0-based index (default: 0 = first sheet)",
)
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Parse and validate only — do not write to DB",
)
parser.add_argument(
    "--truncate",
    action="store_true",
    help="Truncate verified_products before seeding (full re-seed)",
)
args = parser.parse_args()

# ── DB connection ──────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL environment variable is not set.")

# SQLAlchemy needs postgresql:// not postgres://
DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
# Remove asyncpg suffix if present (seed script uses sync psycopg2)
DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def normalize_description(text: str) -> str:
    """Lowercase and strip for consistent matching."""
    if not isinstance(text, str):
        return ""
    return text.strip().lower()

def normalize_hsn(code) -> str:
    """Zero-pad HSN codes to 8 digits. '8471' → '00008471'."""
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return ""
    s = str(code).strip()
    # Remove decimal if Excel stored as float (e.g. "64029990.0")
    s = re.sub(r'\.0+$', '', s)
    s = re.sub(r'[^0-9]', '', s)  # keep digits only
    if not s:
        return ""
    return s.zfill(8)

def normalize_gst(rate) -> float:
    """Parse GST rate to float. '18%' → 18.0, '5' → 5.0."""
    if rate is None or (isinstance(rate, float) and pd.isna(rate)):
        return 0.0
    s = str(rate).strip().replace('%', '')
    try:
        return float(s)
    except ValueError:
        return 0.0

# ── Load Excel ────────────────────────────────────────────────────────────────
if not os.path.exists(args.xlsx):
    sys.exit(f"ERROR: File not found: {args.xlsx}\n"
             f"Place correct_datas.xlsx in the data/ folder or pass --xlsx <path>.")

print(f"📖 Reading {args.xlsx} ...")
try:
    sheet = int(args.sheet) if str(args.sheet).isdigit() else args.sheet
    df = pd.read_excel(args.xlsx, sheet_name=sheet, header=0)
except Exception as e:
    sys.exit(f"ERROR reading Excel: {e}")

print(f"   Columns ({len(df.columns)}): {list(df.columns)}")
print(f"   Rows: {len(df):,}")

# ── Column detection ──────────────────────────────────────────────────────────
# Try to find columns by name first, fall back to position
def find_col(df, names: list, position: int):
    """Find column by name (case-insensitive partial match) or fall back to position index."""
    lower_cols = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower_cols:
            return lower_cols[name.lower()]
    # positional fallback
    if position < len(df.columns):
        return df.columns[position]
    return None

desc_col = find_col(df, ["product description", "description", "product name", "item"], 0)
hsn_col  = find_col(df, ["hsn as per gst", "hsn_as_per_gst", "correct hsn", "hsn code", "hsn"], 4)
gst_col  = find_col(df, ["gst as per gst", "gst_as_per_gst", "correct gst", "gst rate", "gst"], 5)

if not desc_col:
    sys.exit("ERROR: Could not find product description column. Check column names.")
if not hsn_col:
    sys.exit("ERROR: Could not find HSN code column (expected col index 4 = 'HSN As per GST').")
if not gst_col:
    print("WARNING: GST rate column not found — will default to 0.0")

print(f"\n   Mapping:")
print(f"     Description column : '{desc_col}' (col {df.columns.get_loc(desc_col)})")
print(f"     HSN code column    : '{hsn_col}'  (col {df.columns.get_loc(hsn_col)})")
print(f"     GST rate column    : '{gst_col}'  (col {df.columns.get_loc(gst_col) if gst_col else 'N/A'})")

# ── Build rows ────────────────────────────────────────────────────────────────
records = []
skipped = 0

for _, row in df.iterrows():
    desc = str(row[desc_col]).strip() if pd.notna(row[desc_col]) else ""
    hsn  = normalize_hsn(row[hsn_col])
    gst  = normalize_gst(row[gst_col]) if gst_col else 0.0

    if not desc or not hsn:
        skipped += 1
        continue

    records.append({
        "original_description":   desc,
        "description_normalized": normalize_description(desc),
        "hsn_code":               hsn,
        "gst_rate":               gst,
        "source":                 "correct_datas",
    })

print(f"\n   Valid records : {len(records):,}")
print(f"   Skipped (missing desc/hsn): {skipped:,}")

if args.dry_run:
    print("\n✅ Dry run — no changes written.")
    # Print sample
    print("\nSample (first 5 records):")
    for r in records[:5]:
        print(f"  {r['original_description'][:50]:<50} → {r['hsn_code']}  GST {r['gst_rate']}%")
    sys.exit(0)

# ── Write to DB ────────────────────────────────────────────────────────────────
print(f"\n⬆️  Writing {len(records):,} records to verified_products ...")

with engine.begin() as conn:
    if args.truncate:
        conn.execute(text("TRUNCATE TABLE verified_products RESTART IDENTITY"))
        print("   Truncated existing records.")

    # Upsert on description_normalized to avoid duplicates on re-seed
    upsert_sql = text("""
        INSERT INTO verified_products
            (original_description, description_normalized, hsn_code, gst_rate, source)
        VALUES
            (:original_description, :description_normalized, :hsn_code, :gst_rate, :source)
        ON CONFLICT DO NOTHING
    """)

    BATCH = 500
    inserted = 0
    for i in range(0, len(records), BATCH):
        batch = records[i : i + BATCH]
        conn.execute(upsert_sql, batch)
        inserted += len(batch)
        print(f"   {inserted:,} / {len(records):,} inserted...", end="\r")

print(f"\n✅ Done — {inserted:,} records seeded into verified_products.")
print("\nNext steps:")
print("  1. Verify with: psql $DATABASE_URL -c 'SELECT COUNT(*) FROM verified_products;'")
print("  2. Test a product: psql $DATABASE_URL -c \"SELECT hsn_code, gst_rate FROM verified_products WHERE description_normalized = 'vkc dl3323 blue ladies 06';\"")
print("  3. Deploy your updated main.py — Pass 0 will now use this table.")

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

DATABASE_URL = os.environ.get("DATABASE_URL") or input("Paste your Neon DATABASE_URL: ").strip()
# Neon URLs start with postgres:// but SQLAlchemy needs postgresql://
DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

XLSX = os.path.join(os.path.dirname(__file__), "HSN_GST_Master.xlsx")
if not os.path.exists(XLSX):
    sys.exit(f"❌ File not found: {XLSX}\nPlace HSN_GST_Master.xlsx in the data/ folder.")

print("📖 Reading Excel…")
df = pd.read_excel(XLSX, sheet_name="HSN Master", skiprows=2, header=0)
df.columns = ["hsn_code", "description", "gst_rate", "chapter", "category", "notes"]
df = df.dropna(subset=["hsn_code"])
df["hsn_code"]    = df["hsn_code"].astype(str).str.replace(" ", "").str.strip()
df["gst_rate"]    = pd.to_numeric(df["gst_rate"], errors="coerce").fillna(0)
df["chapter"]     = pd.to_numeric(df["chapter"], errors="coerce").fillna(0).astype(int)
df["notes"]       = df["notes"].fillna("").astype(str)
df["description"] = df["description"].fillna("").astype(str)
df["category"]    = df["category"].fillna("").astype(str)

print(f"✅ {len(df)} records loaded. Connecting to DB…")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

CREATE_DDL = text("""
CREATE TABLE IF NOT EXISTS hsn_master (
    id          SERIAL PRIMARY KEY,
    hsn_code    VARCHAR(20) UNIQUE NOT NULL,
    description TEXT,
    gst_rate    NUMERIC(5,2) DEFAULT 0,
    chapter     INT,
    category    VARCHAR(100),
    notes       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_hsn_code     ON hsn_master(hsn_code);
CREATE INDEX IF NOT EXISTS idx_hsn_category ON hsn_master(category);
CREATE INDEX IF NOT EXISTS idx_hsn_rate     ON hsn_master(gst_rate);
""")

UPSERT_SQL = text("""
INSERT INTO hsn_master (hsn_code, description, gst_rate, chapter, category, notes)
VALUES (:hsn_code, :description, :gst_rate, :chapter, :category, :notes)
ON CONFLICT (hsn_code) DO UPDATE SET
    description = EXCLUDED.description,
    gst_rate    = EXCLUDED.gst_rate,
    chapter     = EXCLUDED.chapter,
    category    = EXCLUDED.category,
    notes       = EXCLUDED.notes;
""")

with Session(engine) as session:
    session.execute(CREATE_DDL)
    session.commit()
    print(f"⬆️  Upserting {len(df)} records…")
    session.execute(UPSERT_SQL, df.to_dict(orient="records"))
    session.commit()

host = DATABASE_URL.split("@")[-1].split("/")[0]
print(f"🎉 Done — {len(df)} HSN records seeded into {host}")
