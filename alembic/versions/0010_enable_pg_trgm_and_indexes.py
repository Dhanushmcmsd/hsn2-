"""Enable pg_trgm indexes, FTS on hsn_master, and miss_log for active learning.

Revision ID: 0010_pg_trgm_indexes
Revises: d4e5f6a7b8c9
Create Date: 2026-05-17
"""
from __future__ import annotations

from alembic import op

revision = "0010_pg_trgm_indexes"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def _is_postgresql(connection) -> bool:
    return connection.dialect.name == "postgresql"


def upgrade() -> None:
    conn = op.get_bind()
    if not _is_postgresql(conn):
        return

    with op.get_context().autocommit_block():
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hsn_master_desc_trgm
            ON hsn_master USING GIN (lower(description) gin_trgm_ops)
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hsn_codes_desc_trgm
            ON hsn_codes USING GIN (lower(COALESCE(description, '')) gin_trgm_ops)
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vp_desc_trgm
            ON verified_products USING GIN (lower(description) gin_trgm_ops)
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vp_norm_trgm
            ON verified_products USING GIN (lower(description_normalized) gin_trgm_ops)
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_brand_alias_trgm
            ON brand_aliases USING GIN (lower(brand_name_upper) gin_trgm_ops)
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hsn_master_fts
            ON hsn_master USING GIN (to_tsvector('english', COALESCE(description, '')))
        """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS miss_log (
            id SERIAL PRIMARY KEY,
            product_name TEXT NOT NULL,
            normalized_name TEXT,
            first_token TEXT,
            hit_count INT DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT miss_log_product_name_unique UNIQUE (product_name)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_miss_log_hit_count
        ON miss_log (hit_count DESC, updated_at DESC)
    """)


def downgrade() -> None:
    conn = op.get_bind()
    if not _is_postgresql(conn):
        return

    op.execute("DROP TABLE IF EXISTS miss_log")

    with op.get_context().autocommit_block():
        for idx in (
            "idx_hsn_master_fts",
            "idx_brand_alias_trgm",
            "idx_vp_norm_trgm",
            "idx_vp_desc_trgm",
            "idx_hsn_codes_desc_trgm",
            "idx_hsn_master_desc_trgm",
        ):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {idx}")
