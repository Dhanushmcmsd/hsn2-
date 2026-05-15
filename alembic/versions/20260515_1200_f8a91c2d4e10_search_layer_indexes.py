"""add predictions review index, hsn_codes description trgm, search_history

Revision ID: f8a91c2d4e10
Revises: d3e4f5a6b7c8
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f8a91c2d4e10"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_predictions_review_queue
            ON predictions (needs_review, resolved, created_at)
            WHERE needs_review = true AND resolved = false
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hsn_desc_trgm
            ON hsn_codes USING gin (description gin_trgm_ops)
            """
        )
    else:
        op.create_index(
            "ix_predictions_needs_review_resolved",
            "predictions",
            ["needs_review", "resolved"],
            unique=False,
        )

    op.create_table(
        "search_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("query", sa.String(length=500), nullable=False),
        sa.Column("results_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("top_result_code", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
    )
    op.create_index("ix_search_history_user_id", "search_history", ["user_id"])
    op.create_index("ix_search_history_created_at", "search_history", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.drop_index("ix_search_history_created_at", table_name="search_history")
    op.drop_index("ix_search_history_user_id", table_name="search_history")
    op.drop_table("search_history")

    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_hsn_desc_trgm")
        op.execute("DROP INDEX IF EXISTS idx_predictions_review_queue")
    else:
        op.drop_index("ix_predictions_needs_review_resolved", table_name="predictions")
