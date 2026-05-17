"""Sync verified_products.gst_rate from hsn_master for CBIC-valid rates.

Revision ID: e5f6a7b8c9d0
Revises: 0010_pg_trgm_indexes
Create Date: 2026-05-17 12:00:00
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "e5f6a7b8c9d0"
down_revision = "0010_pg_trgm_indexes"
branch_labels = None
depends_on = None

_SYNC_SQL = text("""
    UPDATE verified_products vp
    SET gst_rate = hm.gst_rate::text
    FROM hsn_master hm
    WHERE vp.hsn_code = hm.hsn_code
      AND (
        vp.gst_rate IS NULL
        OR NULLIF(regexp_replace(vp.gst_rate::text, '[^0-9.]', '', 'g'), '')::numeric
           IS DISTINCT FROM hm.gst_rate::numeric
      )
      AND hm.gst_rate IN (0, 0.1, 0.25, 1.5, 3, 5, 12, 18, 28)
""")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(_SYNC_SQL)


def downgrade() -> None:
    pass
