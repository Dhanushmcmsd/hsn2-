"""add verified_products table

Revision ID: dc1400d4a1cc
Revises: 40a05de8d953
Create Date: 2026-04-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'dc1400d4a1cc'
down_revision = '40a05de8d953'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(table_name)


def upgrade() -> None:
    if not _table_exists('verified_products'):
        op.create_table('verified_products',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('description_normalized', sa.String(length=500), nullable=False),
            sa.Column('hsn_code', sa.String(length=10), nullable=False),
            sa.Column('gst_rate', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_verified_products_id'), 'verified_products', ['id'], unique=False)
        op.create_index(op.f('ix_verified_products_hsn_code'), 'verified_products', ['hsn_code'], unique=False)
        op.create_index('idx_verified_desc', 'verified_products', ['description_normalized'], unique=False)
        op.create_index(op.f('ix_verified_products_description_normalized'), 'verified_products', ['description_normalized'], unique=True)


def downgrade() -> None:
    if _table_exists('verified_products'):
        op.drop_index('ix_verified_products_description_normalized', table_name='verified_products')
        op.drop_index('idx_verified_desc', table_name='verified_products')
        op.drop_index(op.f('ix_verified_products_hsn_code'), table_name='verified_products')
        op.drop_index(op.f('ix_verified_products_id'), table_name='verified_products')
        op.drop_table('verified_products')
