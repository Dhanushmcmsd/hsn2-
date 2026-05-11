"""add_api_key_expiry_fields

Revision ID: 0010_add_api_key_expiry_fields
Revises: 
Create Date: 2026-05-11

NOTE: The ApiKey model already has expires_at, last_used_at, and
rotation_reminder_sent columns declared in the ORM and added via
_ensure_runtime_alters(). This migration is a no-op guard that
makes alembic history consistent with the schema.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0010_add_api_key_expiry_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Idempotent: only add if the column doesn't already exist.
    inspector = sa.inspect(conn)
    existing_cols = {c['name'] for c in inspector.get_columns('api_keys')}

    if 'expires_at' not in existing_cols:
        op.add_column(
            'api_keys',
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True)
        )
    if 'last_used_at' not in existing_cols:
        op.add_column(
            'api_keys',
            sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True)
        )
    if 'rotation_reminder_sent' not in existing_cols:
        op.add_column(
            'api_keys',
            sa.Column(
                'rotation_reminder_sent',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('false')
            )
        )


def downgrade() -> None:
    op.drop_column('api_keys', 'rotation_reminder_sent')
    op.drop_column('api_keys', 'last_used_at')
    op.drop_column('api_keys', 'expires_at')
