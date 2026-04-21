#!/usr/bin/env python3
"""
data/seed_verified.py  —  v2
============================
Seeds (or re-seeds) the verified_products table from product_batches JSON files.

JSON file structure:
  [
    {
      "Description": "Product description",
      "HSN_Ref": "HSN code",
      "GST_Ref": "GST rate",
      "Category_L2": "Category"
    },
    ...
  ]

Two normalised forms are stored per row:
  description_normalized   exact UPPERCASE (unique key, Pass-0A lookup)
  description_no_size      size tokens stripped (Pass-0B fallback lookup)

Usage
-----
  DATABASE_URL="postgresql://..." python data/seed_verified.py
  DATABASE_URL="postgresql://..." python data/seed_verified.py --truncate
  DATABASE_URL="postgresql://..." python data/seed_verified.py --dry-run
  DATABASE_URL="postgresql://..." python data/seed_verified.py --json-dir path/to/dir
"""
import argparse
import glob
import json
import os
import re
import sys

from sqlalchemy import create_engine, text

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Seed verified_products from product_batches JSON files")
parser.add_argument("--json-dir", default=os.path.join(os.path.dirname(__file__), "product_batches"),
                    help="Path to product_batches directory")
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


# ── Load JSON files ────────────────────────────────────────────────────────────────
json_dir = args.json_dir
if not os.path.exists(json_dir):
    sys.exit(f"ERROR: Directory not found: {json_dir}")

files = [f for f in glob.glob(os.path.join(json_dir, '*.json')) if not os.path.basename(f) == '_index.json']
print(f"📖  Reading {len(files)} JSON files from {json_dir} …")

records = []
seen_exact: set[str] = set()

for file_path in files:
    brand = os.path.basename(file_path).replace('.json', '')
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        sys.exit(f"ERROR reading {file_path}: {e}")

    for item in data:
        desc = item.get('Description', '').strip()
        hsn = item.get('HSN_Ref', '')
        gst = item.get('GST_Ref', '')
        cat = item.get('Category_L2', '')

        if not desc or not hsn:
            continue

        desc_norm = desc.upper().strip()
        desc_no_size = strip_sizes(desc)

        if desc_norm in seen_exact:
            continue
        seen_exact.add(desc_norm)

        records.append({
            "description": desc,
            "description_normalized": desc_norm,
            "description_no_size": desc_no_size,
            "hsn_code": hsn,
            "gst_rate": gst,
            "brand": brand,
            "category": cat,
        })

print(f"    Valid records: {len(records):,}")

if args.dry_run:
    print("\n✅  Dry run — no changes written.")
    print("\nSample (first 10):")
    for r in records[:10]:
        print(f"  {r['description'][:45]:<45} | {r['hsn_code']} | {r['gst_rate']} | {r['brand']} | {r['category']}")
    sys.exit(0)


# ── Ensure schema has required columns ──────────────────────────────
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE verified_products ADD COLUMN IF NOT EXISTS description_no_size VARCHAR(500)"))
    conn.execute(text("ALTER TABLE verified_products ADD COLUMN IF NOT EXISTS brand VARCHAR(100)"))
    conn.execute(text("ALTER TABLE verified_products ADD COLUMN IF NOT EXISTS category VARCHAR(100)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_verified_no_size ON verified_products (description_no_size)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_verified_brand ON verified_products (brand)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_verified_category ON verified_products (category)"))


# ── Write to DB ───────────────────────────────────────────────────────────────
print(f"\n⬆️   Writing {len(records):,} records to verified_products …")

upsert_sql = text("""
    INSERT INTO verified_products
        (description, description_normalized, description_no_size, hsn_code, gst_rate, brand, category)
    VALUES
        (:description, :description_normalized, :description_no_size, :hsn_code, :gst_rate, :brand, :category)
    ON CONFLICT (description_normalized) DO UPDATE SET
        description_no_size = EXCLUDED.description_no_size,
        hsn_code            = EXCLUDED.hsn_code,
        gst_rate            = EXCLUDED.gst_rate,
        brand               = EXCLUDED.brand,
        category            = EXCLUDED.category
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
print("  psql $DATABASE_URL -c \"SELECT description, hsn_code, gst_rate, brand, category")
print("    FROM verified_products WHERE brand = 'TATA' LIMIT 5;\"")
