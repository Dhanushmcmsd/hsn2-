"""seed product_batches JSON into verified_products + Malayalam aliases + VKC brand aliases

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16 17:00:00
"""
from __future__ import annotations

import glob
import json
import os
import re

from alembic import op
from sqlalchemy import text

# revision identifiers
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

# ── helpers ──────────────────────────────────────────────────────────────────
_SIZE_PAT = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|'
    r'PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB)\b'
    r'|\b\d+\s*X\s*\d+\b|\b\d+\s*\+\s*\d+\b'
    r'|\b\d+S\b|\b\d+N\b|\b\d+P\b|\b\d+\b',
    re.IGNORECASE,
)


def _strip_sizes(text_val: str) -> str:
    t = _SIZE_PAT.sub(' ', text_val.upper())
    t = re.sub(r'[^A-Z\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _clean_hsn(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    digits = re.sub(r'[^0-9]', '', str(raw).strip())
    return digits.zfill(8) if digits else None


def _clean_gst(raw) -> str | None:
    if not raw or (isinstance(raw, float) and raw != raw):
        return None
    m = re.search(r'(\d+(?:\.\d+)?)', str(raw))
    return m.group(1) + '%' if m else None


def _sp_exec(conn, sql, params=None):
    """Execute SQL wrapped in a SAVEPOINT so a failure never aborts the outer
    transaction.  Returns True on success, False on error."""
    conn.execute(text("SAVEPOINT _mig_sp"))
    try:
        if params is not None:
            conn.execute(sql, params)
        else:
            conn.execute(sql)
        conn.execute(text("RELEASE SAVEPOINT _mig_sp"))
        return True
    except Exception as exc:  # noqa: BLE001
        conn.execute(text("ROLLBACK TO SAVEPOINT _mig_sp"))
        print(f"  [savepoint rollback] {exc}")
        return False


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Ensure brand/category columns exist (idempotent) ───────────────────
    for col_sql in [
        "ALTER TABLE verified_products ADD COLUMN IF NOT EXISTS brand    VARCHAR(200)",
        "ALTER TABLE verified_products ADD COLUMN IF NOT EXISTS category VARCHAR(100)",
    ]:
        _sp_exec(conn, text(col_sql))

    # ── 2. Seed all product_batches JSON files ────────────────────────────────
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..')
    )
    batch_dir = os.path.join(repo_root, 'data', 'product_batches')
    files = sorted(glob.glob(os.path.join(batch_dir, '*.json')))
    files = [f for f in files if not os.path.basename(f).startswith('_index')]

    print(f"[migration b2c3] Seeding {len(files)} product batch files...")

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
            brand               = COALESCE(EXCLUDED.brand,
                                           verified_products.brand),
            category            = COALESCE(EXCLUDED.category,
                                           verified_products.category)
    """)

    total_inserted = 0
    total_skipped  = 0

    for filepath in files:
        brand_name = os.path.splitext(os.path.basename(filepath))[0].upper()
        try:
            with open(filepath, encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            print(f"  [skip file] {filepath}: {exc}")
            continue

        if not isinstance(data, list):
            continue

        batch_rows = []
        for item in data:
            desc    = str(item.get('Description', '') or '').strip()
            raw_hsn = _clean_hsn(item.get('HSN_Ref', ''))
            raw_gst = _clean_gst(item.get('GST_Ref', ''))
            if not desc or not raw_hsn:
                continue
            norm     = desc.upper().strip()
            no_size  = _strip_sizes(desc)
            category = str(item.get('Category', '') or '').strip() or None
            batch_rows.append({
                'description': desc,
                'norm':        norm,
                'no_size':     no_size,
                'brand':       brand_name,
                'category':    category,
                'hsn_code':    raw_hsn,
                'gst_rate':    raw_gst,
            })

        if not batch_rows:
            continue

        ok = _sp_exec(conn, upsert_sql, batch_rows)
        if ok:
            total_inserted += len(batch_rows)
        else:
            # Row-by-row fallback so one bad row doesn't lose the whole file
            for row in batch_rows:
                if _sp_exec(conn, upsert_sql, [row]):
                    total_inserted += 1
                else:
                    total_skipped  += 1

    print(f"[migration b2c3] Products: {total_inserted} upserted, {total_skipped} skipped.")

    # ── 3. Re-activate inactive language_aliases ──────────────────────────────
    ok = _sp_exec(conn, text("""
        UPDATE language_aliases
        SET is_active = TRUE
        WHERE is_active = FALSE AND weight >= 1.0
    """))
    if ok:
        print("[migration b2c3] language_aliases reactivated.")

    # ── 4. Malayalam staple aliases ───────────────────────────────────────────
    malayalam_aliases = [
        ('\u0d06\u0d1f\u0d4d\u0d1f',         '\u0d06\u0d1f\u0d4d\u0d1f',         '11010000', 'ml', 2.0),
        ('\u0d05\u0d30\u0d3f',               '\u0d05\u0d30\u0d3f',               '10063000', 'ml', 2.0),
        ('\u0d2a\u0d1e\u0d4d\u0d1a\u0d38\u0d3e\u0d30', '\u0d2a\u0d1e\u0d4d\u0d1a\u0d38\u0d3e\u0d30', '17011200', 'ml', 2.0),
        ('\u0d0e\u0d23\u0d4d\u0d23',         '\u0d0e\u0d23\u0d4d\u0d23',         '15079000', 'ml', 2.0),
        ('\u0d09\u0d2a\u0d4d\u0d2a\u0d4d',  '\u0d09\u0d2a\u0d4d\u0d2a\u0d4d',  '25010010', 'ml', 2.0),
        ('\u0d1a\u0d3e\u0d2f',               '\u0d1a\u0d3e\u0d2f',               '09024090', 'ml', 2.0),
        ('\u0d15\u0d3e\u0d2a\u0d4d\u0d2a\u0d3f', '\u0d15\u0d3e\u0d2a\u0d4d\u0d2a\u0d3f', '09011100', 'ml', 2.0),
        ('\u0d2a\u0d3e\u0d32\u0d4d',         '\u0d2a\u0d3e\u0d32\u0d4d',         '04011000', 'ml', 2.0),
        ('\u0d2e\u0d41\u0d1f\u0d4d\u0d1f',  '\u0d2e\u0d41\u0d1f\u0d4d\u0d1f',  '04070090', 'ml', 2.0),
        ('\u0d12\u0d31\u0d4d\u0d31\u0d3f\u0d1a\u0d4d\u0d1a\u0d15\u0d4d\u0d15\u0d31\u0d3f', '\u0d12\u0d31\u0d4d\u0d31\u0d3f\u0d1a\u0d4d\u0d1a\u0d15\u0d4d\u0d15\u0d31\u0d3f', '27101190', 'ml', 1.5),
        ('CHAKKA',    'CHAKKA',    '08109020', 'ml-roman', 2.0),
        ('CHERUPAYAR','CHERUPAYAR','07134000', 'ml-roman', 2.0),
        ('CHERUMANI', 'CHERUMANI', '07133200', 'ml-roman', 2.0),
        ('PAYAR',     'PAYAR',     '07134000', 'ml-roman', 2.0),
        ('VAZHAKKA',  'VAZHAKKA',  '08030010', 'ml-roman', 2.0),
        ('THENGA',    'THENGA',    '18010000', 'ml-roman', 2.0),
        ('MEEN',      'MEEN',      '03020000', 'ml-roman', 2.0),
        ('KOORI',     'KOORI',     '02071200', 'ml-roman', 2.0),
        ('NAADAN',    'NAADAN',    '04011000', 'ml-roman', 1.5),
    ]

    alias_sql = text("""
        INSERT INTO language_aliases
            (term, term_normalized, hsn_code, language, weight, is_active)
        VALUES
            (:term, :norm, :hsn, :lang, :weight, TRUE)
        ON CONFLICT (term_normalized) DO UPDATE SET
            is_active = TRUE,
            weight    = GREATEST(language_aliases.weight, EXCLUDED.weight)
    """)
    inserted_aliases = 0
    for row in malayalam_aliases:
        params = {'term': row[0], 'norm': row[1], 'hsn': row[2],
                  'lang': row[3], 'weight': row[4]}
        if _sp_exec(conn, alias_sql, params):
            inserted_aliases += 1
    print(f"[migration b2c3] {inserted_aliases}/{len(malayalam_aliases)} Malayalam aliases upserted.")

    # ── 5. Kerala/store brand aliases ─────────────────────────────────────────
    store_brands = [
        ('VKC',        '64021200', 5.0,  'footwear'),
        ('PARAGON',    '64021200', 5.0,  'footwear'),
        ('NIRAPARA',   '11010000', 0.0,  'flour'),
        ('BRAHMINS',   '21039090', 18.0, 'condiments'),
        ('EASTERN',    '09109100', 5.0,  'spices'),
        ('AVT',        '09024090', 5.0,  'tea'),
        ('MOOLYA',     '11010000', 0.0,  'flour'),
        ('APAAR',      '11010000', 0.0,  'flour'),
        ('ALFA',       '11010000', 0.0,  'flour'),
        ('ALLTIME',    '11010000', 0.0,  'flour'),
        ('BISMI',      '22011000', 0.0,  'water'),
        ('AHARA',      '11010000', 0.0,  'rice flour'),
        ('ASHTAPATHY', '30049099', 12.0, 'medicine'),
        ('CHANDRIKA',  '34011150', 18.0, 'soap'),
        ('COCHIN',     '21039090', 18.0, 'condiments'),
        ('COLOMBO',    '09109100', 5.0,  'spices'),
        ('HAWKINS',    '73239300', 12.0, 'cookware'),
        ('PRESTIGE',   '73239300', 12.0, 'cookware'),
        ('BUTTERFLY',  '84145100', 18.0, 'fan'),
        ('CELLO',      '39241090', 18.0, 'plasticware'),
        ('MILTON',     '39241090', 18.0, 'plasticware'),
    ]

    brand_sql = text("""
        INSERT INTO brand_aliases
            (brand_name, hsn_code, gst_rate, category)
        VALUES
            (:brand, :hsn, :gst, :cat)
        ON CONFLICT (brand_name) DO UPDATE SET
            hsn_code = EXCLUDED.hsn_code,
            gst_rate = EXCLUDED.gst_rate,
            category = EXCLUDED.category
    """)
    inserted_brands = 0
    for (brand, hsn, gst, cat) in store_brands:
        if _sp_exec(conn, brand_sql, {'brand': brand, 'hsn': hsn, 'gst': gst, 'cat': cat}):
            inserted_brands += 1
    print(f"[migration b2c3] {inserted_brands}/{len(store_brands)} store/Kerala brand_aliases upserted.")
    print("[migration b2c3] Complete.")


def downgrade() -> None:
    pass
