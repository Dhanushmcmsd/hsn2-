"""add_gst_rate_history

Revision ID: f7e2a1b3c904
Revises:     a1b2c3d4e5f6
Create Date: 2026-05-11 13:53:00.000000

What this migration does
------------------------
Creates the ``gst_rate_history`` table to store historical GST rate periods
per HSN code. Each row represents one effective rate window for a given code.
A NULL ``effective_to`` means the rate is currently active.

Columns
-------
- id               SERIAL PRIMARY KEY
- hsn_code         VARCHAR(10)   NOT NULL, indexed
- gst_rate         FLOAT         NOT NULL
- effective_from   DATE          NOT NULL
- effective_to     DATE          NULL  (NULL = currently active)
- source_url       VARCHAR(500)  NULL
- fetched_at       TIMESTAMPTZ   NOT NULL  DEFAULT now()
"""
from alembic import op
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Revision identifiers — used by Alembic
# ---------------------------------------------------------------------------
revision = 'f7e2a1b3c904'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'gst_rate_history',
        sa.Column('id',             sa.Integer(),                  nullable=False),
        sa.Column('hsn_code',       sa.String(length=10),          nullable=False),
        sa.Column('gst_rate',       sa.Float(),                    nullable=False),
        sa.Column('effective_from', sa.Date(),                     nullable=False),
        sa.Column('effective_to',   sa.Date(),                     nullable=True),
        sa.Column('source_url',     sa.String(length=500),         nullable=True),
        sa.Column(
            'fetched_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_gst_rate_history')),
    )
    # Index for fast per-HSN-code lookups and range queries
    op.create_index(
        'ix_gst_rate_history_hsn_code',
        'gst_rate_history',
        ['hsn_code'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_gst_rate_history_hsn_code', table_name='gst_rate_history')
    op.drop_table('gst_rate_history')
