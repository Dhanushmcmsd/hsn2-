"""add_organisation_branch_models

Revision ID: 0002_add_organisation_branch_models
Revises: 
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0002_add_organisation_branch_models'
down_revision = None  # set to your latest revision ID if one exists
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create organisations table
    op.create_table(
        'organisations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('gstin_prefix', sa.String(15), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # 2. Create branches table with FK to organisations
    op.create_table(
        'branches',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('organisation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('state_code', sa.String(2), nullable=True),
        sa.Column('gstin', sa.String(15), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
        sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organisation_id', 'name', name='uq_branch_org_name'),
    )

    # 3. ALTER TABLE users ADD COLUMN branch_id
    op.add_column('users', sa.Column('branch_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_users_branch_id', 'users', 'branches', ['branch_id'], ['id'])

    # 4. ALTER TABLE predictions ADD COLUMN branch_id
    op.add_column('predictions', sa.Column('branch_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_predictions_branch_id', 'predictions', 'branches', ['branch_id'], ['id'])

    # 5. ALTER TABLE api_keys ADD COLUMN branch_id
    op.add_column('api_keys', sa.Column('branch_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_api_keys_branch_id', 'api_keys', 'branches', ['branch_id'], ['id'])

    # 6. Add indexes
    op.create_index('idx_predictions_branch', 'predictions', ['branch_id'])
    op.create_index('idx_users_branch', 'users', ['branch_id'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_users_branch', table_name='users')
    op.drop_index('idx_predictions_branch', table_name='predictions')

    # Drop FK constraints and columns in reverse order
    op.drop_constraint('fk_api_keys_branch_id', 'api_keys', type_='foreignkey')
    op.drop_column('api_keys', 'branch_id')

    op.drop_constraint('fk_predictions_branch_id', 'predictions', type_='foreignkey')
    op.drop_column('predictions', 'branch_id')

    op.drop_constraint('fk_users_branch_id', 'users', type_='foreignkey')
    op.drop_column('users', 'branch_id')

    op.drop_table('branches')
    op.drop_table('organisations')
