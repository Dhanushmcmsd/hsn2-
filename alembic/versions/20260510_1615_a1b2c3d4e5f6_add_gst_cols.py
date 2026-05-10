"""add_gst_cols

Revision ID: a1b2c3d4e5f6
Revises:     e1a4c9d8f201
Create Date: 2026-05-10 16:15:00.000000

What this migration does
------------------------
1. Adds 4 GST-related columns to the existing ``hsn_codes`` table:
     - gst_rate_numeric     NUMERIC(5, 2)   — precise GST percentage (18.00, 5.00 …)
     - gst_effective_from   DATE            — rate start date
     - gst_effective_to     DATE            — rate end date  (NULL = currently active)
     - gst_updated_at       TIMESTAMPTZ     — last sync timestamp, auto-set by DB

2. Creates ``gst_change_log`` table for a full GST-rate audit trail.

All changes are fully reversible via downgrade().
"""
from alembic import op
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Revision identifiers — used by Alembic
# ---------------------------------------------------------------------------
revision = 'a1b2c3d4e5f6'
down_revision = 'e1a4c9d8f201'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add GST rate columns to hsn_codes
    # ------------------------------------------------------------------
    # NOTE: The ORM model uses ``gst_rate_numeric`` to avoid shadowing the
    # legacy ``gst_rate FLOAT`` column that already exists on this table.
    with op.batch_alter_table('hsn_codes', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'gst_rate_numeric',
                sa.Numeric(precision=5, scale=2),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                'gst_effective_from',
                sa.Date(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                'gst_effective_to',
                sa.Date(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                'gst_updated_at',
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.text('now()'),
            )
        )

    # ------------------------------------------------------------------
    # 2. Create gst_change_log audit table
    # ------------------------------------------------------------------
    op.create_table(
        'gst_change_log',
        sa.Column('id',         sa.Integer(),                         nullable=False),
        sa.Column('hsn_code',   sa.String(length=10),                 nullable=False),
        sa.Column('old_rate',   sa.Numeric(precision=5, scale=2),     nullable=True),
        sa.Column('new_rate',   sa.Numeric(precision=5, scale=2),     nullable=True),
        sa.Column(
            'changed_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column('source',     sa.String(length=50),                 nullable=True),
        sa.Column('notes',      sa.Text(),                            nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_gst_change_log')),
    )
    # Index for fast per-HSN-code audit lookups
    op.create_index(
        'ix_gst_change_log_hsn_code',
        'gst_change_log',
        ['hsn_code'],
        unique=False,
    )
    # Index for time-range queries (e.g. "changes in the last 7 days")
    op.create_index(
        'ix_gst_change_log_changed_at',
        'gst_change_log',
        ['changed_at'],
        unique=False,
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 2. Drop gst_change_log (reverse order of creation)
    # ------------------------------------------------------------------
    op.drop_index('ix_gst_change_log_changed_at', table_name='gst_change_log')
    op.drop_index('ix_gst_change_log_hsn_code',   table_name='gst_change_log')
    op.drop_table('gst_change_log')

    # ------------------------------------------------------------------
    # 1. Remove GST columns from hsn_codes
    # ------------------------------------------------------------------
    with op.batch_alter_table('hsn_codes', schema=None) as batch_op:
        batch_op.drop_column('gst_updated_at')
        batch_op.drop_column('gst_effective_to')
        batch_op.drop_column('gst_effective_from')
        batch_op.drop_column('gst_rate_numeric')
