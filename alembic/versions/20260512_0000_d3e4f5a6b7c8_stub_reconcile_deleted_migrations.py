"""stub: reconcile deleted migration revisions

This stub exists so Alembic can locate the revision 'd3e4f5a6b7c8' that was
stamped in the production database by commits that were subsequently reverted.
It performs no DDL changes — the schema is already correct from earlier
migrations. The sole purpose is to give Alembic a chain it can walk.

Revision ID: d3e4f5a6b7c8
Revises: e1a4c9d8f201
Create Date: 2026-05-12 00:00:00
"""
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "e1a4c9d8f201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: this revision only exists to satisfy the Alembic revision chain.
    pass


def downgrade() -> None:
    pass
