"""backfill verified description_no_size

Revision ID: e1a4c9d8f201
Revises: b9f3c6a21d77
Create Date: 2026-04-23 22:30:00.000000
"""
from alembic import op
from sqlalchemy import inspect


revision = "e1a4c9d8f201"
down_revision = "b9f3c6a21d77"
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
    if bind.dialect.name != "postgresql":
        return
    if not _table_exists("verified_products") or not _column_exists("verified_products", "description_no_size"):
        return

    op.execute(
        r"""
        UPDATE verified_products
        SET description_no_size = UPPER(
            REGEXP_REPLACE(
                REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        UPPER(description),
                        '\m\d+(\.\d+)?\s*(G|GM|GMS|KG|KGS|ML|L|LTR|PC|PCS|NOS|MG|OZ|LB)\M',
                        ' ',
                        'gi'
                    ),
                    '\m\d+\s*X\s*\d+\M|\m\d+\s*\+\s*\d+\M|\m\d+\M',
                    ' ',
                    'g'
                ),
                '\s+',
                ' ',
                'g'
            )
        )
        WHERE description_no_size IS NULL OR description_no_size = ''
        """
    )


def downgrade() -> None:
    # Data backfill only; no schema rollback.
    return
