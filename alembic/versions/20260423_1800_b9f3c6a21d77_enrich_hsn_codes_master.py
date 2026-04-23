"""enrich hsn_codes master columns

Revision ID: b9f3c6a21d77
Revises: 7c8e1d2b4f10
Create Date: 2026-04-23 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b9f3c6a21d77"
down_revision = "7c8e1d2b4f10"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _table_exists("hsn_codes"):
        return

    additions = [
        ("hsn_chapter", sa.String(length=2), None),
        ("hsn_heading", sa.String(length=4), None),
        ("hsn_subheading", sa.String(length=6), None),
        ("cbic_description", sa.Text(), None),
        ("parent_heading_desc", sa.Text(), None),
        ("gst_rate", sa.Float(), None),
        ("category", sa.String(length=100), None),
        ("schedule", sa.String(length=150), None),
        ("is_active", sa.Boolean(), sa.text("TRUE")),
    ]

    for name, column_type, default in additions:
        if _column_exists("hsn_codes", name):
            continue
        kwargs = {"nullable": True}
        if default is not None:
            kwargs["server_default"] = default
            kwargs["nullable"] = False
        op.add_column("hsn_codes", sa.Column(name, column_type, **kwargs))


def downgrade() -> None:
    if not _table_exists("hsn_codes"):
        return

    for name in [
        "is_active",
        "schedule",
        "category",
        "gst_rate",
        "parent_heading_desc",
        "cbic_description",
        "hsn_subheading",
        "hsn_heading",
        "hsn_chapter",
    ]:
        if _column_exists("hsn_codes", name):
            op.drop_column("hsn_codes", name)
