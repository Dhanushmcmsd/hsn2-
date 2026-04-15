"""add hsn_codes table

Revision ID: 40a05de8d953
Revises: 
Create Date: 2026-04-15 19:48:06.602975
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '40a05de8d953'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(table_name)


def upgrade() -> None:
    # users, predictions, api_keys already exist in production Neon DB.
    # Only create them if they are genuinely missing (e.g. fresh environment).

    if not _table_exists('users'):
        op.create_table('users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('hashed_password', sa.String(length=255), nullable=False),
            sa.Column('full_name', sa.String(length=255), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=True),
            sa.Column('is_admin', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
        op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)

    if not _table_exists('predictions'):
        op.create_table('predictions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('request_id', sa.String(length=36), nullable=False),
            sa.Column('input_text', sa.Text(), nullable=False),
            sa.Column('predicted_hsn', sa.String(length=20), nullable=False),
            sa.Column('confidence', sa.Float(), nullable=False),
            sa.Column('needs_review', sa.Boolean(), nullable=True),
            sa.Column('resolved', sa.Boolean(), nullable=True),
            sa.Column('corrected_hsn', sa.String(length=20), nullable=True),
            sa.Column('api_key_hash', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_predictions_id'), 'predictions', ['id'], unique=False)
        op.create_index(op.f('ix_predictions_request_id'), 'predictions', ['request_id'], unique=True)

    if not _table_exists('api_keys'):
        op.create_table('api_keys',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('key_hash', sa.String(length=64), nullable=True),
            sa.Column('label', sa.String(length=100), nullable=True),
            sa.Column('tier', sa.String(length=20), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=True),
            sa.Column('requests_today', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'], unique=True)

    if not _table_exists('hsn_codes'):
        op.create_table('hsn_codes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('hsn_code', sa.String(length=10), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('source', sa.String(length=50), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_hsn_codes_hsn_code'), 'hsn_codes', ['hsn_code'], unique=True)
        op.create_index(op.f('ix_hsn_codes_id'), 'hsn_codes', ['id'], unique=False)


def downgrade() -> None:
    if _table_exists('hsn_codes'):
        op.drop_index(op.f('ix_hsn_codes_id'), table_name='hsn_codes')
        op.drop_index(op.f('ix_hsn_codes_hsn_code'), table_name='hsn_codes')
        op.drop_table('hsn_codes')
