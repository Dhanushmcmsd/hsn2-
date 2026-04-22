#!/usr/bin/env python3
"""
data/seed.py — v4
==================
Seeds verified_products from correct_datas.xlsx (or product_batches JSON).

Key improvements in v4:
- Always populates description_no_size (needed for Pass 0B/0C)
- Adds brand/category columns when available
- Idempotent: uses ON CONFLICT DO UPDATE
- Works with or without description_no_size column existing (adds it)

Usage
-----
  # Seed from xlsx (default)
  DATABASE_URL="postgresql://..." python data/seed.py

  # From batch JSONs
  DATABASE_URL="postgresql://..." python data/seed.py --source batch

  # Dry run
  DATABASE_URL="postgresql://..." python data/seed.py --dry-run

  # Force re-seed (truncate first)
  DATABASE_URL="postgresql://..." python data/seed.py --truncate
"""
import argparse, glob, json, os, re, sys
import pandas as pd
from sqlalchemy import create_engine, text

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--source", choices=["batch", "xlsx"], default="xlsx",
                    help="Data source: 'batch' (JSON files) or 'xlsx' (default)")
parser.add_argument("--batch-dir",
                    default=os.path.join(os.path.dirname(__file__), "product_batches"))
parser.add_argument("--xlsx",
                    default=os.path.join(os.path.dirname(__file__), "correct_datas.xlsx"))
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
    """Remove weight/volume/count tokens; collapse whitespace; return UPPERCASE."""
    t = _SIZE_PAT.sub(' ', text.upper())
    t = re.sub(r'[^A-Z\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def clean_hsn(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    digits = re.sub(r'[^0-9]', '', str(raw).strip())
    return digits.zfill(8) if digits else None

def clean_gst(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    m = re.search(r'(\d+(?:\.\d+)?)', str(raw))
    return m.group(1) + '%' if m else None

# ── Ensure schema ─────────────────────────────────────────────────────────────
print("🔧  Ensuring schema is up to date …")
with engine.begin() as conn:
    # Create table if missing
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS verified_products (
            id                       SERIAL PRIMARY KEY,
            description              TEXT NOT NULL,
            description_normalized   VARCHAR(500) NOT NULL,
            description_no_size      VARCHAR(500),
            hsn_code                 VARCHAR(10) NOT NULL,
            gst_rate                 VARCHAR(20),
            brand                    VARCHAR(100),
            category                 VARCHAR(100),
            created_at               TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_vp_desc_norm UNIQUE (description_normalized)
        )
    """))
    # Add columns if missing (idempotent)
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
            pass
    # Indexes
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_verified_no_size   ON verified_products (description_no_size)",
        "CREATE INDEX IF NOT EXISTS idx_verified_brand     ON verified_products (brand)",
        "CREATE INDEX IF NOT EXISTS idx_verified_category  ON verified_products (category)",
        "CREATE INDEX IF NOT EXISTS idx_verified_hsn       ON verified_products (hsn_code)",
    ]:
        try:
            conn.execute(text(idx_sql))
        except Exception:
            pass
print("    Schema ready ✓")

# ── Load data ─────────────────────────────────────────────────────────────────
# Each item: (description, hsn, gst, category, brand)
raw_records: list[tuple] = []

if args.source == "batch" and os.path.isdir(args.batch_dir):
    print(f"📂  Loading from batch JSONs: {args.batch_dir}")
    files = sorted(glob.glob(os.path.join(args.batch_dir, "*.json")))
    files = [f for f in files if not os.path.basename(f).startswith('_')]
    print(f"    {len(files)} batch files found")
    for f in files:
        brand = os.path.basename(f).replace('.json', '')
        try:
            with open(f) as fh:
                data = json.loads(fh.read().strip() or "[]")
            if isinstance(data, dict):
                continue
            for item in data:
                if isinstance(item, dict) and 'Description' in item:
                    raw_records.append((
                        item['Description'],
                        item.get('HSN_Ref', ''),
                        item.get('GST_Ref', ''),
                        item.get('Category_L2', ''),
                        brand
                    ))
        except Exception as e:
            print(f"    ⚠ Could not read {f}: {e}")
    print(f"    {len(raw_records):,} records loaded")

else:
    # Default: load from xlsx (correct_datas.xlsx)
    xlsx_path = args.xlsx
    if not os.path.exists(xlsx_path):
        sys.exit(f"ERROR: {xlsx_path} not found. Copy correct_datas.xlsx to data/ folder.")

    print(f"📖  Loading from {xlsx_path}")
    df = pd.read_excel(xlsx_path, sheet_name=0, header=0)
    cols = df.columns.tolist()
    print(f"    Columns: {cols}")

    def _find(candidates, pos):
        cl = {c.lower(): c for c in cols}
        for c in candidates:
            if c.lower() in cl:
                return cl[c.lower()]
        return cols[pos] if pos < len(cols) else None

    desc_col = _find(["description", "product description", "product name", "item name"], 0)
    hsn_col  = _find(["hsn_sac (as per the gst)", "hsn_sac", "hsn as per gst",
                      "hsn_as_per_gst", "hsn code", "hsn"], 1)
    gst_col  = _find(["gst(as per the gst)", "gst as per the gst", "gst as per gst",
                      "gst_as_per_gst", "gst rate", "gst"], 2)

    if not desc_col or not hsn_col:
        sys.exit(f"ERROR: Could not find required columns. desc={desc_col}, hsn={hsn_col}, available={cols}")

    print(f"    Using: desc='{desc_col}' | hsn='{hsn_col}' | gst='{gst_col}'")

    for _, row in df.iterrows():
        raw_records.append((
            str(row.get(desc_col, '') or '').strip(),
            row.get(hsn_col, ''),
            row.get(gst_col, '') if gst_col else '',
            '',   # no category in xlsx
            ''    # no brand in xlsx
        ))
    print(f"    {len(raw_records):,} rows loaded")

# ── Build clean records ────────────────────────────────────────────────────────
records = []
seen_exact: set[str] = set()
skipped = 0

for (desc, hsn_raw, gst_raw, category, brand) in raw_records:
    desc = str(desc).strip()
    hsn  = clean_hsn(hsn_raw)
    gst  = clean_gst(gst_raw)
    if not desc or desc.lower() == 'nan' or not hsn:
        skipped += 1
        continue

    desc_norm    = desc.upper().strip()
    desc_no_size = strip_sizes(desc)

    if desc_norm in seen_exact:
        skipped += 1
        continue
    seen_exact.add(desc_norm)

    records.append({
        "description":            desc,
        "description_normalized": desc_norm,
        "description_no_size":    desc_no_size or None,
        "brand":                  brand.strip() if brand else None,
        "category":               (category if category and category != 'Other_Unclassified' else None),
        "hsn_code":               hsn,
        "gst_rate":               gst,
    })

print(f"\n    Valid records    : {len(records):,}")
print(f"    Skipped          : {skipped:,}")
categorized = sum(1 for r in records if r['category'])
with_no_size = sum(1 for r in records if r['description_no_size'])
print(f"    With category    : {categorized:,}")
print(f"    With no_size     : {with_no_size:,}")

# ── Sample ─────────────────────────────────────────────────────────────────────
print("\nSample (first 5):")
for r in records[:5]:
    print(f"  {r['description'][:45]:<45} | HSN:{r['hsn_code']} | GST:{r['gst_rate']}")
    print(f"  {'':45}   no_size: {r['description_no_size']}")

if args.dry_run:
    print("\n✅  Dry run — no changes written.")
    sys.exit(0)

# ── Upsert records ─────────────────────────────────────────────────────────────
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

print(f"\n⬆️   Writing {len(records):,} records …")
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
        pct = int(inserted / len(records) * 100)
        print(f"    {inserted:,} / {len(records):,} ({pct}%) …", end="\r")

print(f"\n✅  Done — {inserted:,} records upserted.")

# ── Back-fill description_no_size for any NULL rows ───────────────────────────
print("\n🔄  Back-filling NULL description_no_size values …")
with engine.begin() as conn:
    # For PostgreSQL: use regexp_replace to strip sizes inline
    # This is a simplified version - the Python strip_sizes is more accurate
    # but we can do a basic version in SQL for any NULLs
    result = conn.execute(text("""
        SELECT COUNT(*) FROM verified_products
        WHERE description_no_size IS NULL
    """))
    null_count = result.scalar()
    if null_count > 0:
        print(f"    {null_count} rows have NULL description_no_size")
        print("    Run python with --truncate and re-seed to fix all rows.")
    else:
        print("    All rows have description_no_size ✓")

print("\nVerify with:")
print('  psql $DATABASE_URL -c "SELECT COUNT(*) FROM verified_products;"')
print('  psql $DATABASE_URL -c \'SELECT description, hsn_code, description_no_size')
print('    FROM verified_products WHERE description_normalized LIKE \'\'%SESAME%\'\'\'')
print('    LIMIT 5;"')