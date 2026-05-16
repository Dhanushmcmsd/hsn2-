"""migrate all static data: hsn_codes.csv, correct_datas.xlsx, product_batches, csv.json

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-16 19:00:00

What this migration does
------------------------
1. Seeds data/hsn_codes.csv  →  hsn_codes table
   (~900 WCO/GST chapter-level codes that are the backbone of HSN lookup)

2. Seeds data/correct_datas.xlsx  →  verified_products table
   (manually curated products with confirmed HSN + GST values)

3. Upserts data/product_batches/*.json  →  verified_products table
   (brand-level product lists already seeded by b2c3 migration;
   this migration re-runs them safely with ON CONFLICT DO UPDATE)

4. Seeds data/csv.json  →  pending_products table (creates it if needed)
   (products with blank HSN codes awaiting classification by the app)
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re

from alembic import op
from sqlalchemy import text

revision      = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on    = None

# ─── helpers ────────────────────────────────────────────────────────────────

_SIZE_PAT = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|'
    r'PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB|PACK|PKT|BOX|BTL|BOTTLE|TIN|JAR|CAN|SACHET|BAG|POUCH)\b'
    r'|\b\d+\s*X\s*\d+\b|\b\d+\s*\+\s*\d+\b'
    r'|\b\d+S\b|\b\d+N\b|\b\d+P\b',
    re.IGNORECASE,
)


def _strip_sizes(t: str) -> str:
    t = _SIZE_PAT.sub(' ', t.upper())
    t = re.sub(r'[^A-Z\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _clean_hsn(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    d = re.sub(r'[^0-9]', '', str(raw).strip())
    return d.zfill(8) if d else None


def _clean_gst(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    m = re.search(r'(\d+(?:\.\d+)?)', str(raw))
    return m.group(1) + '%' if m else None


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


# ─── STEP 1 : hsn_codes.csv → hsn_codes ─────────────────────────────────────

def _seed_hsn_csv(conn) -> None:
    csv_path = os.path.join(_repo_root(), 'data', 'hsn_codes.csv')
    if not os.path.exists(csv_path):
        print('[c3d4] hsn_codes.csv not found — skipping HSN seed')
        return

    rows: list[dict] = []
    with open(csv_path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_code = re.sub(r'[^0-9]', '', str(row.get('hsn_code', '')).strip())
            if not raw_code:
                continue
            code = raw_code.zfill(8) if len(raw_code) <= 8 else raw_code
            desc = str(row.get('description', '')).strip()
            if not desc:
                continue
            rows.append({
                'hsn_code':       code,
                'hsn_chapter':    code[:2],
                'hsn_heading':    code[:4],
                'hsn_subheading': code[:6],
                'description':    desc,
                'source':         'WCO_HS_CSV',
                'is_active':      True,
            })

    if not rows:
        print('[c3d4] No rows parsed from hsn_codes.csv')
        return

    inserted = 0
    for item in rows:
        try:
            r = conn.execute(text("""
                INSERT INTO hsn_codes
                    (hsn_code, hsn_chapter, hsn_heading, hsn_subheading,
                     description, source, is_active)
                VALUES
                    (:hsn_code, :hsn_chapter, :hsn_heading, :hsn_subheading,
                     :description, :source, :is_active)
                ON CONFLICT (hsn_code) DO UPDATE SET
                    description = EXCLUDED.description,
                    source      = EXCLUDED.source,
                    is_active   = EXCLUDED.is_active
            """), item)
            inserted += 1
        except Exception as exc:
            print(f'[c3d4] hsn row error {item["hsn_code"]}: {exc}')

    print(f'[c3d4] hsn_codes: {inserted}/{len(rows)} upserted from CSV')


# ─── STEP 2 : correct_datas.xlsx → verified_products ────────────────────────

def _seed_xlsx(conn) -> None:
    try:
        import openpyxl
    except ImportError:
        print('[c3d4] openpyxl not available — skipping xlsx seed')
        return

    xlsx_path = os.path.join(_repo_root(), 'data', 'correct_datas.xlsx')
    if not os.path.exists(xlsx_path):
        print('[c3d4] correct_datas.xlsx not found — skipping')
        return

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h else '' for h in next(rows_iter, [])]

    def _col(candidates, fallback_pos):
        hl = {h.lower(): i for i, h in enumerate(headers)}
        for c in candidates:
            if c.lower() in hl:
                return hl[c.lower()]
        return fallback_pos if fallback_pos < len(headers) else None

    desc_i = _col(['description', 'product description', 'product name', 'item name'], 0)
    hsn_i  = _col(['hsn_sac (as per the gst)', 'hsn_sac', 'hsn as per gst',
                   'hsn_as_per_gst', 'hsn code', 'hsn'], 1)
    gst_i  = _col(['gst(as per the gst)', 'gst as per the gst', 'gst rate', 'gst'], 2)

    inserted = 0
    skipped  = 0
    for raw_row in rows_iter:
        if desc_i is None or len(raw_row) <= desc_i:
            continue
        desc    = str(raw_row[desc_i] or '').strip()
        hsn_raw = raw_row[hsn_i]  if (hsn_i  is not None and len(raw_row) > hsn_i)  else ''
        gst_raw = raw_row[gst_i]  if (gst_i  is not None and len(raw_row) > gst_i)  else ''

        hsn = _clean_hsn(hsn_raw)
        gst = _clean_gst(gst_raw)
        if not desc or desc.lower() == 'nan' or not hsn:
            skipped += 1
            continue

        norm    = desc.upper().strip()
        no_size = _strip_sizes(desc)

        try:
            conn.execute(text("""
                INSERT INTO verified_products
                    (description, description_normalized, description_no_size,
                     hsn_code, gst_rate)
                VALUES
                    (:desc, :norm, :no_size, :hsn, :gst)
                ON CONFLICT (description_normalized) DO UPDATE SET
                    hsn_code            = EXCLUDED.hsn_code,
                    gst_rate            = EXCLUDED.gst_rate,
                    description_no_size = COALESCE(EXCLUDED.description_no_size,
                                                   verified_products.description_no_size)
            """), {'desc': desc, 'norm': norm, 'no_size': no_size,
                   'hsn': hsn, 'gst': gst})
            inserted += 1
        except Exception as exc:
            print(f'[c3d4] xlsx row error: {desc[:40]}: {exc}')
            skipped += 1

    wb.close()
    print(f'[c3d4] correct_datas.xlsx: {inserted} upserted, {skipped} skipped')


# ─── STEP 3 : product_batches/*.json → verified_products ────────────────────

def _seed_batches(conn) -> None:
    batch_dir = os.path.join(_repo_root(), 'data', 'product_batches')
    files     = sorted(glob.glob(os.path.join(batch_dir, '*.json')))
    files     = [f for f in files if not os.path.basename(f).startswith('_index')]

    if not files:
        print('[c3d4] No product_batches/*.json files found — skipping')
        return

    total = 0
    upsert = text("""
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

    for filepath in files:
        brand_name = os.path.splitext(os.path.basename(filepath))[0].upper()
        try:
            with open(filepath, encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception as exc:
            print(f'[c3d4]   skip {brand_name}: {exc}')
            continue

        if not isinstance(data, list):
            continue

        batch = []
        for item in data:
            desc = str(item.get('Description', '') or '').strip()
            hsn  = _clean_hsn(item.get('HSN_Ref', ''))
            gst  = _clean_gst(item.get('GST_Ref', ''))
            if not desc or not hsn:
                continue
            batch.append({
                'description': desc,
                'norm':        desc.upper().strip(),
                'no_size':     _strip_sizes(desc),
                'brand':       brand_name,
                'category':    str(item.get('Category', '') or '').strip() or None,
                'hsn_code':    hsn,
                'gst_rate':    gst,
            })

        if batch:
            try:
                conn.execute(upsert, batch)
                total += len(batch)
            except Exception as exc:
                print(f'[c3d4]   error {brand_name}: {exc}')

    print(f'[c3d4] product_batches: {total} rows upserted from {len(files)} files')


# ─── STEP 4 : csv.json → pending_products ───────────────────────────────────

def _seed_csv_json(conn) -> None:
    # Create pending_products table if it doesn't exist
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pending_products (
                id              SERIAL PRIMARY KEY,
                product_name    TEXT NOT NULL,
                source_name     VARCHAR(500),
                pack_or_size    VARCHAR(200),
                hsn_code        VARCHAR(20),
                status          VARCHAR(50) DEFAULT 'pending',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_pending_product_name UNIQUE (product_name)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_products (status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_pending_source ON pending_products (source_name)"
        ))
    except Exception as exc:
        print(f'[c3d4] pending_products table create error: {exc}')

    csv_json_path = os.path.join(_repo_root(), 'data', 'csv.json')
    if not os.path.exists(csv_json_path):
        print('[c3d4] csv.json not found — skipping pending_products seed')
        return

    try:
        with open(csv_json_path, encoding='utf-8') as fh:
            items = json.load(fh)
    except Exception as exc:
        print(f'[c3d4] csv.json parse error: {exc}')
        return

    if not isinstance(items, list):
        print('[c3d4] csv.json is not a list — skipping')
        return

    inserted = 0
    for item in items:
        product_name = str(item.get('product_name', '') or '').strip()
        if not product_name:
            continue
        source_name  = str(item.get('source_name', '') or '').strip() or None
        pack_or_size = str(item.get('pack_or_size', '') or '').strip() or None
        hsn_code     = str(item.get('hsn_code', '') or '').strip() or None
        status       = str(item.get('status', 'pending') or 'pending').strip()

        try:
            conn.execute(text("""
                INSERT INTO pending_products
                    (product_name, source_name, pack_or_size, hsn_code, status)
                VALUES
                    (:product_name, :source_name, :pack_or_size, :hsn_code, :status)
                ON CONFLICT (product_name) DO UPDATE SET
                    hsn_code    = COALESCE(EXCLUDED.hsn_code, pending_products.hsn_code),
                    status      = EXCLUDED.status,
                    updated_at  = NOW()
            """), {
                'product_name': product_name,
                'source_name':  source_name,
                'pack_or_size': pack_or_size,
                'hsn_code':     hsn_code,
                'status':       status,
            })
            inserted += 1
        except Exception as exc:
            print(f'[c3d4] pending_products row error: {product_name}: {exc}')

    print(f'[c3d4] csv.json: {inserted} pending products upserted')


# ─── upgrade / downgrade ─────────────────────────────────────────────────────

def upgrade() -> None:
    conn = op.get_bind()

    print('[c3d4] Starting full static-data migration...')

    # Step 1 — HSN master codes from CSV
    _seed_hsn_csv(conn)

    # Step 2 — Manually curated products from xlsx
    _seed_xlsx(conn)

    # Step 3 — Brand product batches from JSON files
    _seed_batches(conn)

    # Step 4 — Pending products queue from csv.json
    _seed_csv_json(conn)

    print('[c3d4] All static data migration complete.')


def downgrade() -> None:
    # Data-only migration — downgrade is intentionally a no-op
    # to prevent accidental deletion of production data.
    pass
