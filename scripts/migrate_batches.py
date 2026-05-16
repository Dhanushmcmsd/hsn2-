#!/usr/bin/env python3
"""
scripts/migrate_batches.py
==========================
Standalone runner to seed data/product_batches/*.json into verified_products
without running a full Alembic deploy.  Useful for local re-seeding or
one-off batch additions.

Usage
-----
    DATABASE_URL="postgresql://..." python scripts/migrate_batches.py
    DATABASE_URL="postgresql://..." python scripts/migrate_batches.py --dry-run
    DATABASE_URL="postgresql://..." python scripts/migrate_batches.py --brand BRAHMINS
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

from sqlalchemy import create_engine, text

parser = argparse.ArgumentParser()
parser.add_argument('--dry-run',  action='store_true')
parser.add_argument('--brand',    default=None, help='Only seed this brand file (e.g. BRAHMINS)')
parser.add_argument('--batch-dir', default=None)
args = parser.parse_args()

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not DATABASE_URL:
    sys.exit('ERROR: DATABASE_URL is required.')
DATABASE_URL = (
    DATABASE_URL
    .replace('postgres://', 'postgresql://', 1)
    .replace('postgresql+asyncpg://', 'postgresql://', 1)
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
batch_dir = args.batch_dir or os.path.join(repo_root, 'data', 'product_batches')

_SIZE_PAT = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|'
    r'PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB)\b'
    r'|\b\d+\s*X\s*\d+\b|\b\d+\s*\+\s*\d+\b'
    r'|\b\d+S\b|\b\d+N\b|\b\d+P\b|\b\d+\b',
    re.IGNORECASE,
)

def strip_sizes(t: str) -> str:
    t = _SIZE_PAT.sub(' ', t.upper())
    t = re.sub(r'[^A-Z\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def clean_hsn(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    d = re.sub(r'[^0-9]', '', str(raw).strip())
    return d.zfill(8) if d else None

def clean_gst(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    m = re.search(r'(\d+(?:\.\d+)?)', str(raw))
    return m.group(1) + '%' if m else None

if args.brand:
    files = [os.path.join(batch_dir, f'{args.brand.upper()}.json')]
else:
    files = sorted(glob.glob(os.path.join(batch_dir, '*.json')))
    files = [f for f in files if not os.path.basename(f).startswith('_index')]

print(f'Found {len(files)} batch file(s) in {batch_dir}')

upsert_sql = text("""
    INSERT INTO verified_products
        (description, description_normalized, description_no_size,
         brand, category, hsn_code, gst_rate)
    VALUES
        (:description, :norm, :no_size,
         :brand, :category, :hsn_code, :gst_rate)
    ON CONFLICT (description_normalized) DO UPDATE SET
        hsn_code            = EXCLUDED.hsn_code,
        gst_rate            = EXCLUDED.gst_rate,
        description_no_size = COALESCE(EXCLUDED.description_no_size,
                                       verified_products.description_no_size),
        brand               = COALESCE(EXCLUDED.brand, verified_products.brand),
        category            = COALESCE(EXCLUDED.category, verified_products.category)
""")

total = 0
with engine.begin() as conn:
    for filepath in files:
        brand_name = os.path.splitext(os.path.basename(filepath))[0].upper()
        try:
            with open(filepath, encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception as exc:
            print(f'  [skip] {brand_name}: {exc}')
            continue

        if not isinstance(data, list):
            continue

        rows = []
        for item in data:
            desc = str(item.get('Description', '') or '').strip()
            hsn = clean_hsn(item.get('HSN_Ref', ''))
            gst = clean_gst(item.get('GST_Ref', ''))
            if not desc or not hsn:
                continue
            rows.append({
                'description': desc,
                'norm': desc.upper().strip(),
                'no_size': strip_sizes(desc),
                'brand': brand_name,
                'category': str(item.get('Category', '') or '').strip() or None,
                'hsn_code': hsn,
                'gst_rate': gst,
            })

        if not rows:
            continue

        if args.dry_run:
            print(f'  [dry] {brand_name}: {len(rows)} rows would be upserted')
            total += len(rows)
            continue

        try:
            conn.execute(upsert_sql, rows)
            print(f'  ✅  {brand_name}: {len(rows)} rows upserted')
            total += len(rows)
        except Exception as exc:
            print(f'  ❌  {brand_name}: {exc}')

print(f'\nTotal: {total} rows {"(dry run)" if args.dry_run else "upserted"}.')
