#!/usr/bin/env python3
"""
data/seed_verified.py  —  v3
============================
Seeds the verified_products table from the brand-split batch JSONs
(product_batches/ folder) which contain Category_L2 for better routing.

Falls back to correct_datas.xlsx if batch folder is missing.

Batch JSON record format:
  {
    "Category_L2": "Dairy_Milk",
    "Description": "AMUL GOLD FULL CREAM MILK 500ML",
    "HSN_Ref":     "04011000",
    "GST_Ref":     "GST 5%"
  }

correct_datas.xlsx column layout:
  Col 0  →  Description
  Col 1  →  HSN_SAC (As per The GST)
  Col 2  →  GST(As Per The GST)

Usage
-----
  # Recommended: seed from batch JSONs (includes Category_L2)
  DATABASE_URL="postgresql://..." python data/seed_verified.py

  # Force reload from xlsx instead
  DATABASE_URL="postgresql://..." python data/seed_verified.py --source xlsx

  # Dry run (no DB writes)
  DATABASE_URL="postgresql://..." python data/seed_verified.py --dry-run

  # Full re-seed (truncate first)
  DATABASE_URL="postgresql://..." python data/seed_verified.py --truncate
"""
import argparse, glob, json, os, re, sys
import pandas as pd
from sqlalchemy import create_engine, text

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--source", choices=["batch", "xlsx"], default="batch",
                    help="Data source: 'batch' (JSON files) or 'xlsx'")
parser.add_argument("--batch-dir", default=os.path.join(os.path.dirname(__file__), "product_batches"),
                    help="Directory containing brand JSON files")
parser.add_argument("--xlsx", default=os.path.join(os.path.dirname(__file__), "correct_datas.xlsx"))
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--truncate", action="store_true")
args = parser.parse_args()

# ── DB connection ─────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL environment variable is not set.")
DATABASE_URL = (DATABASE_URL
    .replace("postgres://", "postgresql://", 1)
    .replace("postgresql+asyncpg://", "postgresql://", 1))
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# ── Normalisation helpers ─────────────────────────────────────────────────────
_SIZE_PAT = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|'
    r'PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB)\b'
    r'|\b\d+\s*X\s*\d+\b|\b\d+\s*\+\s*\d+\b'
    r'|\b\d+S\b|\b\d+N\b|\b\d+P\b|\b\d+\b',
    re.IGNORECASE,
)

def strip_sizes(text: str) -> str:
    t = _SIZE_PAT.sub(' ', text.upper())
    t = re.sub(r'[^A-Z\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def clean_hsn(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw): return None
    digits = re.sub(r'[^0-9]', '', str(raw).strip())
    return digits.zfill(8) if digits else None

def clean_gst(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw): return None
    m = re.search(r'(\d+)', str(raw))
    return m.group(1) + '%' if m else None

# ── Load data ─────────────────────────────────────────────────────────────────
raw_records = []   # list of (description, hsn, gst, category)

if args.source == "batch" and os.path.isdir(args.batch_dir):
    print(f"📂  Loading from batch JSONs: {args.batch_dir}")
    files = sorted(glob.glob(os.path.join(args.batch_dir, "*.json")))
    print(f"    {len(files)} batch files found")
    for f in files:
        with open(f) as fh:
            raw = fh.read().strip()
            if not raw: continue
            data = json.loads(raw)
            if isinstance(data, dict): continue   # skip _index.json
            for item in data:
                if not isinstance(item, dict) or 'Description' not in item:
                    continue
                raw_records.append((
                    item['Description'],
                    item.get('HSN_Ref', ''),
                    item.get('GST_Ref', ''),
                    item.get('Category_L2', ''),
                ))
    print(f"    {len(raw_records):,} product records loaded")
else:
    if args.source == "batch":
        print(f"⚠️   Batch dir not found ({args.batch_dir}), falling back to xlsx")
    print(f"📖  Loading from {args.xlsx}")
    if not os.path.exists(args.xlsx):
        sys.exit(f"ERROR: {args.xlsx} not found")
    df = pd.read_excel(args.xlsx, sheet_name=0, header=0)
    cols = df.columns.tolist()

    def _find(candidates, pos):
        cl = {c.lower(): c for c in cols}
        for c in candidates:
            if c.lower() in cl: return cl[c.lower()]
        return cols[pos] if pos < len(cols) else None

    desc_col = _find(["description", "product description"], 0)
    hsn_col  = _find(["hsn_sac (as per the gst)", "hsn_sac", "hsn code", "hsn"], 1)
    gst_col  = _find(["gst(as per the gst)", "gst as per the gst", "gst rate", "gst"], 2)
    print(f"    Columns: desc='{desc_col}' hsn='{hsn_col}' gst='{gst_col}'")

    for _, row in df.iterrows():
        raw_records.append((
            str(row.get(desc_col, '') or '').strip(),
            row.get(hsn_col, ''),
            row.get(gst_col, ''),
            '',   # no category in xlsx
        ))
    print(f"    {len(raw_records):,} rows loaded")

# ── Build clean records ────────────────────────────────────────────────────────
records = []
seen_exact: set[str] = set()
skipped = 0

for (desc, hsn_raw, gst_raw, category) in raw_records:
    desc = str(desc).strip()
    hsn  = clean_hsn(hsn_raw)
    gst  = clean_gst(gst_raw)
    if not desc or not hsn:
        skipped += 1
        continue

    desc_norm    = desc.upper().strip()
    desc_no_size = strip_sizes(desc)

    # Brand = first alpha token (for routing hints)
    brand_match = re.match(r'^([A-Z][A-Z0-9]*)', desc_norm)
    brand = brand_match.group(1) if brand_match else ''

    if desc_norm in seen_exact:
        skipped += 1
        continue
    seen_exact.add(desc_norm)

    records.append({
        "description":            desc,
        "description_normalized": desc_norm,
        "description_no_size":    desc_no_size,
        "brand":                  brand,
        "category":               category if category and category != 'Other_Unclassified' else '',
        "hsn_code":               hsn,
        "gst_rate":               gst,
    })

print(f"\n    Valid records  : {len(records):,}")
print(f"    Skipped        : {skipped:,}")
categorized = sum(1 for r in records if r['category'])
print(f"    With category  : {categorized:,}")

if args.dry_run:
    print("\n✅  Dry run — no changes written.")
    print("\nSample (first 10):")
    for r in records[:10]:
        print(f"  {r['description'][:40]:<40} | {r['hsn_code']} | {r['gst_rate']} "
              f"| {r['category'] or 'no-cat'}")
    sys.exit(0)

# ── Ensure schema is up to date ────────────────────────────────────────────────
print("\n🔧  Ensuring schema columns exist …")
with engine.begin() as conn:
    # Add new columns if they don't exist (idempotent)
    for col_def in [
        "description_no_size VARCHAR(500)",
        "brand               VARCHAR(100)",
        "category            VARCHAR(100)",
    ]:
        col_name = col_def.split()[0]
        try:
            conn.execute(text(
                f"ALTER TABLE verified_products ADD COLUMN IF NOT EXISTS {col_def}"
            ))
        except Exception:
            pass  # column already exists

    # Indexes
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_verified_no_size ON verified_products (description_no_size)",
        "CREATE INDEX IF NOT EXISTS idx_verified_brand   ON verified_products (brand)",
        "CREATE INDEX IF NOT EXISTS idx_verified_category ON verified_products (category)",
    ]:
        try:
            conn.execute(text(idx_sql))
        except Exception:
            pass

# ── Upsert records ─────────────────────────────────────────────────────────────
print(f"\n⬆️   Writing {len(records):,} records …")

upsert_sql = text("""
    INSERT INTO verified_products
        (description, description_normalized, description_no_size,
         brand, category, hsn_code, gst_rate)
    VALUES
        (:description, :description_normalized, :description_no_size,
         :brand, :category, :hsn_code, :gst_rate)
    ON CONFLICT (description_normalized) DO UPDATE SET
        description_no_size = EXCLUDED.description_no_size,
        brand               = EXCLUDED.brand,
        category            = EXCLUDED.category,
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

print(f"\n✅  Done — {inserted:,} records upserted.")
print("\nVerify with:")
print('  psql $DATABASE_URL -c "SELECT COUNT(*) FROM verified_products;"')
print('  psql $DATABASE_URL -c "SELECT brand, category, hsn_code, gst_rate')
print('    FROM verified_products WHERE description_normalized = \'TATA SALT IODISED 1KG\';"')
