"""close_open_ended_gst_history_rows

Revision ID: c9d8e7f6a5b4
Revises:     f7e2a1b3c904
Create Date: 2026-05-11 21:00:00.000000
"""
from alembic import op


revision = "c9d8e7f6a5b4"
down_revision = "f7e2a1b3c904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                hsn_code,
                effective_from,
                ROW_NUMBER() OVER (
                    PARTITION BY hsn_code
                    ORDER BY effective_from DESC, id DESC
                ) AS rn,
                LAG(effective_from) OVER (
                    PARTITION BY hsn_code
                    ORDER BY effective_from DESC, id DESC
                ) AS next_effective_from
            FROM gst_rate_history
            WHERE effective_to IS NULL
        )
        UPDATE gst_rate_history g
        SET effective_to = ranked.next_effective_from - INTERVAL '1 day'
        FROM ranked
        WHERE g.id = ranked.id
          AND ranked.rn > 1
          AND ranked.next_effective_from IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uix_gst_history_active
        ON gst_rate_history (hsn_code)
        WHERE effective_to IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uix_gst_history_active;")
