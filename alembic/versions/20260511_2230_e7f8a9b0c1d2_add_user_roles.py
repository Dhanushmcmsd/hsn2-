"""add_user_roles

Revision ID: e7f8a9b0c1d2
Revises:     d4e5f6a7b8c9
Create Date: 2026-05-11 22:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "e7f8a9b0c1d2"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=50), nullable=False, server_default="branch_user"),
    )
    op.add_column("users", sa.Column("region_code", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "region_code")
    op.drop_column("users", "role")
