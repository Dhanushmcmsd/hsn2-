"""Enable pg_trgm extension and add GIN trigram indexes for fast search.

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-16 12:00:00
"""
from __future__ import annotations

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_verified_trgm_norm
            ON verified_products
            USING gin(description_normalized gin_trgm_ops)
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_verified_trgm_nosize
            ON verified_products
            USING gin(description_no_size gin_trgm_ops)
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hsn_codes_fts
            ON hsn_codes
            USING gin(to_tsvector('english', description))
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hsn_codes_trgm
            ON hsn_codes
            USING gin(description gin_trgm_ops)
        """)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_verified_trgm_norm")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_verified_trgm_nosize")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_hsn_codes_fts")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_hsn_codes_trgm")
