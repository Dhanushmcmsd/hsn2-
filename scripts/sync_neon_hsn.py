#!/usr/bin/env python3
"""
Additive upsert of hsn_codes into Neon/Postgres from data/hsn_codes.csv.

Uses psycopg2 execute_values for fast batched upserts (non-destructive:
deactivates stale padded placeholders instead of DELETE).

Requires DATABASE_URL (postgresql:// or postgresql+asyncpg://).
"""
from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

import psycopg2
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "hsn_codes.csv"


def _pg_dsn(database_url: str) -> str:
    url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(url)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    db = (parsed.path or "/").lstrip("/") or "postgres"
    return f"host={host} port={port} dbname={db} user={user} password={password} sslmode=require"


def _read_master_csv() -> list[tuple]:
    lines = CSV_PATH.read_text(encoding="utf-8").splitlines()
    data_lines = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
    rows: list[tuple] = []
    for row in csv.DictReader(data_lines):
        code = re.sub(r"[^0-9]", "", str(row.get("hsn_code", "")).strip()).zfill(8)
        if len(code) != 8:
            continue
        desc = str(row.get("description", "")).strip()
        gst_raw = str(row.get("gst_rate", "")).strip()
        gst_rate = float(gst_raw) if gst_raw else None
        rows.append(
            (code, code[:2], code[:4], code[:6], desc, desc, gst_rate, "CBIC_GST_MASTER", True)
        )
    return rows


def _is_padded_placeholder(code: str) -> bool:
    if code.endswith("0000") and code[4:8] == "0000":
        return True
    if code.endswith("00") and code[6:8] == "00":
        return code[:6] + "00" == code
    return False


def sync() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    records = _read_master_csv()
    target_codes = {r[0] for r in records}
    print(f"Loaded {len(records)} codes from {CSV_PATH}")

    conn = psycopg2.connect(_pg_dsn(database_url))
    conn.autocommit = False
    cur = conn.cursor()

    upsert_sql = """
        INSERT INTO hsn_codes (
            hsn_code, hsn_chapter, hsn_heading, hsn_subheading,
            description, cbic_description, gst_rate, source, is_active
        ) VALUES %s
        ON CONFLICT (hsn_code) DO UPDATE SET
            hsn_chapter = EXCLUDED.hsn_chapter,
            hsn_heading = EXCLUDED.hsn_heading,
            hsn_subheading = EXCLUDED.hsn_subheading,
            description = EXCLUDED.description,
            cbic_description = EXCLUDED.cbic_description,
            gst_rate = EXCLUDED.gst_rate,
            source = EXCLUDED.source,
            is_active = TRUE
    """
    execute_values(cur, upsert_sql, records, page_size=1000)

    cur.execute("SELECT hsn_code FROM hsn_codes WHERE COALESCE(is_active, TRUE) = TRUE")
    existing = {row[0] for row in cur.fetchall()}
    stale_placeholders = [c for c in (existing - target_codes) if _is_padded_placeholder(c)]
    if stale_placeholders:
        cur.execute(
            """
            UPDATE hsn_codes
            SET is_active = FALSE, source = 'DEPRECATED_PLACEHOLDER'
            WHERE hsn_code = ANY(%s)
            """,
            (stale_placeholders,),
        )

    cur.execute("""
        INSERT INTO hsn_search (hsn_code, search_vector)
        SELECT hsn_code,
               to_tsvector('simple',
                   coalesce(description,'') || ' ' || coalesce(cbic_description,''))
        FROM hsn_codes
        WHERE COALESCE(is_active, TRUE) = TRUE
        ON CONFLICT (hsn_code) DO UPDATE
            SET search_vector = EXCLUDED.search_vector
    """)

    conn.commit()
    cur.close()
    conn.close()
    print(f"Upserted: {len(records)}, deactivated placeholders: {len(stale_placeholders)}")


if __name__ == "__main__":
    sync()
