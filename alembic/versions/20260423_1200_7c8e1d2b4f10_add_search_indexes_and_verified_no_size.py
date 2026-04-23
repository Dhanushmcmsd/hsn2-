"""add search indexes and verified no-size support

Revision ID: 7c8e1d2b4f10
Revises: dc1400d4a1cc
Create Date: 2026-04-23 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "7c8e1d2b4f10"
down_revision = "dc1400d4a1cc"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(table_name):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    if _table_exists("verified_products") and not _column_exists("verified_products", "description_no_size"):
        op.add_column("verified_products", sa.Column("description_no_size", sa.String(length=500), nullable=True))

    if _table_exists("verified_products"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_verified_no_size ON verified_products (description_no_size)"
        )
        if bind.dialect.name == "postgresql":
            op.execute(
                "CREATE INDEX IF NOT EXISTS idx_vp_trgm_norm "
                "ON verified_products USING gin (description_normalized gin_trgm_ops)"
            )
            op.execute(
                "CREATE INDEX IF NOT EXISTS idx_vp_trgm_no_size "
                "ON verified_products USING gin (description_no_size gin_trgm_ops)"
            )

    if _table_exists("hsn_codes"):
        has_category = _column_exists("hsn_codes", "category")
        if bind.dialect.name == "postgresql":
            weighted_vector = (
                "setweight(to_tsvector('english', description), 'A') || "
                "setweight(to_tsvector('english', COALESCE(category, '')), 'B')"
                if has_category
                else "setweight(to_tsvector('english', description), 'A')"
            )
            op.execute(
                "CREATE INDEX IF NOT EXISTS idx_hsn_weighted_fts "
                f"ON hsn_codes USING gin ({weighted_vector})"
            )
            op.execute(
                "CREATE INDEX IF NOT EXISTS idx_hsn_code_prefix "
                "ON hsn_codes (hsn_code text_pattern_ops)"
            )
        else:
            op.execute(
                "CREATE INDEX IF NOT EXISTS idx_hsn_code_prefix ON hsn_codes (hsn_code)"
            )


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists("hsn_codes"):
        op.execute("DROP INDEX IF EXISTS idx_hsn_code_prefix")
        if bind.dialect.name == "postgresql":
            op.execute("DROP INDEX IF EXISTS idx_hsn_weighted_fts")

    if _table_exists("verified_products"):
        op.execute("DROP INDEX IF EXISTS idx_verified_no_size")
        if bind.dialect.name == "postgresql":
            op.execute("DROP INDEX IF EXISTS idx_vp_trgm_norm")
            op.execute("DROP INDEX IF EXISTS idx_vp_trgm_no_size")
        if _column_exists("verified_products", "description_no_size"):
            op.drop_column("verified_products", "description_no_size")
