"""Migrate all static data: hsn_codes.csv, correct_datas.xlsx, csv.json → pending_products

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-16 19:00:00
"""
from __future__ import annotations

import csv
import json
import os
import re

from alembic import op
from sqlalchemy import text

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


# ── helpers ────────────────────────────────────────────────────────────────
def _sp_exec(conn, sql, params=None):
    """Run SQL inside a SAVEPOINT.  Rolls back to savepoint on error so the
    outer Alembic transaction stays alive."""
    conn.execute(text("SAVEPOINT _c3d4_sp"))
    try:
        if params is not None:
            conn.execute(sql, params)
        else:
            conn.execute(sql)
        conn.execute(text("RELEASE SAVEPOINT _c3d4_sp"))
        return True
    except Exception as exc:  # noqa: BLE001
        conn.execute(text("ROLLBACK TO SAVEPOINT _c3d4_sp"))
        print(f"  [savepoint rollback] {exc}")
        return False


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


def upgrade() -> None:
    conn = op.get_bind()

    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..')
    )

    # ── Step 1: pending_products table ────────────────────────────────────────
    _sp_exec(conn, text("""
        CREATE TABLE IF NOT EXISTS pending_products (
            id           SERIAL PRIMARY KEY,
            product_name TEXT        NOT NULL UNIQUE,
            source_name  VARCHAR(500),
            pack_or_size VARCHAR(200),
            hsn_code     VARCHAR(20),
            status       VARCHAR(50)  NOT NULL DEFAULT 'pending',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ
        )
    """))

    # ── Step 2: hsn_codes.csv → hsn_codes ────────────────────────────────────
    hsn_csv = os.path.join(repo_root, 'data', 'hsn_codes.csv')
    if os.path.isfile(hsn_csv):
        upsert_hsn = text("""
            INSERT INTO hsn_codes (hsn_code, description)
            VALUES (:hsn_code, :description)
            ON CONFLICT (hsn_code) DO UPDATE
                SET description = EXCLUDED.description
        """)
        inserted = skipped = 0
        try:
            with open(hsn_csv, encoding='utf-8-sig') as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    # Accept flexible column names
                    hsn  = _clean_hsn(
                        row.get('HSNCode') or row.get('hsn_code')
                        or row.get('HSN Code') or row.get('code') or ''
                    )
                    desc = (
                        row.get('Description') or row.get('description')
                        or row.get('HSNDescription') or ''
                    ).strip()
                    if not hsn or not desc:
                        skipped += 1
                        continue
                    ok = _sp_exec(conn, upsert_hsn, {'hsn_code': hsn, 'description': desc})
                    if ok:
                        inserted += 1
                    else:
                        skipped += 1
            print(f"[c3d4] hsn_codes.csv: {inserted} inserted, {skipped} skipped.")
        except Exception as exc:
            print(f"[c3d4] hsn_codes.csv read error: {exc}")
    else:
        print("[c3d4] hsn_codes.csv not found — skipping.")

    # ── Step 3: correct_datas.xlsx → verified_products ────────────────────────
    xlsx_path = os.path.join(repo_root, 'data', 'correct_datas.xlsx')
    if os.path.isfile(xlsx_path):
        try:
            import openpyxl  # noqa: PLC0415 — runtime optional dep
            wb   = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
            ws   = wb.active
            rows = list(ws.iter_rows(values_only=True))
            wb.close()

            if rows:
                # Auto-detect header row
                header = [str(c).strip().lower() if c else '' for c in rows[0]]

                def _col(*names):
                    for n in names:
                        if n in header:
                            return header.index(n)
                    return None

                ci_desc = _col('description', 'product', 'product name', 'name')
                ci_hsn  = _col('hsn_code', 'hsn code', 'hsncode', 'hsn')
                ci_gst  = _col('gst_rate', 'gst rate', 'gst', 'tax')

                if ci_desc is None or ci_hsn is None:
                    print("[c3d4] correct_datas.xlsx: cannot detect description/hsn columns — skip.")
                else:
                    upsert_vp = text("""
                        INSERT INTO verified_products
                            (description, description_normalized, description_no_size,
                             hsn_code, gst_rate)
                        VALUES
                            (:description, :norm, :no_size, :hsn_code, :gst_rate)
                        ON CONFLICT (description_normalized) DO UPDATE SET
                            hsn_code = EXCLUDED.hsn_code,
                            gst_rate = COALESCE(EXCLUDED.gst_rate,
                                                verified_products.gst_rate)
                    """)
                    ins = skp = 0
                    for r in rows[1:]:
                        desc = str(r[ci_desc] or '').strip() if ci_desc < len(r) else ''
                        hsn  = _clean_hsn(r[ci_hsn] if ci_hsn < len(r) else '')
                        gst  = _clean_gst(r[ci_gst] if ci_gst is not None and ci_gst < len(r) else '')
                        if not desc or not hsn:
                            skp += 1
                            continue
                        norm    = desc.upper().strip()
                        no_size = re.sub(r'\s+', ' ',
                                         re.sub(r'[^A-Z\s]', ' ',
                                                re.sub(r'\b\d+[A-Za-z]*\b', ' ', norm))).strip()
                        ok = _sp_exec(conn, upsert_vp, {
                            'description': desc, 'norm': norm,
                            'no_size': no_size, 'hsn_code': hsn, 'gst_rate': gst,
                        })
                        if ok:
                            ins += 1
                        else:
                            skp += 1
                    print(f"[c3d4] correct_datas.xlsx: {ins} inserted, {skp} skipped.")
        except ImportError:
            print("[c3d4] openpyxl not installed — skipping correct_datas.xlsx")
        except Exception as exc:
            print(f"[c3d4] correct_datas.xlsx error: {exc}")
    else:
        print("[c3d4] correct_datas.xlsx not found — skipping.")

    # ── Step 4: csv.json → pending_products ───────────────────────────────────
    csv_json = os.path.join(repo_root, 'data', 'csv.json')
    if os.path.isfile(csv_json):
        try:
            with open(csv_json, encoding='utf-8') as fh:
                items = json.load(fh)
            if not isinstance(items, list):
                items = [items]

            ins_p = skp_p = 0
            pending_sql = text("""
                INSERT INTO pending_products
                    (product_name, source_name, pack_or_size, hsn_code, status)
                VALUES
                    (:product_name, :source_name, :pack_or_size, :hsn_code, 'pending')
                ON CONFLICT (product_name) DO NOTHING
            """)
            for item in items:
                name = (
                    str(item.get('Description') or item.get('product_name')
                        or item.get('name') or '').strip()
                )
                if not name:
                    skp_p += 1
                    continue
                hsn = _clean_hsn(
                    item.get('HSN_Ref') or item.get('hsn_code') or item.get('HSN') or ''
                )
                ok = _sp_exec(conn, pending_sql, {
                    'product_name': name,
                    'source_name':  str(item.get('source_name', '') or '').strip() or None,
                    'pack_or_size': str(item.get('Pack_or_Size', '') or '').strip() or None,
                    'hsn_code':     hsn,
                })
                if ok:
                    ins_p += 1
                else:
                    skp_p += 1
            print(f"[c3d4] csv.json: {ins_p} pending products inserted, {skp_p} skipped.")
        except Exception as exc:
            print(f"[c3d4] csv.json error: {exc}")
    else:
        print("[c3d4] csv.json not found — skipping.")

    print("[c3d4] Complete.")


def downgrade() -> None:
    pass
