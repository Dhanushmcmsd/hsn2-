"""add_audit_log_table

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2025-05-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('actor_user_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('actor_role', sa.String(50), nullable=True),
        sa.Column('branch_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('branches.id'), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', sa.String(100), nullable=True),
        sa.Column('old_value', postgresql.JSONB(), nullable=True),
        sa.Column('new_value', postgresql.JSONB(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=True),
    )
    op.create_index('idx_audit_log_timestamp', 'audit_log', ['timestamp'],
                    postgresql_ops={'timestamp': 'DESC'})
    op.create_index('idx_audit_log_event_type', 'audit_log', ['event_type'])

    # Immutability: revoke UPDATE and DELETE from PUBLIC, grant INSERT+SELECT to app_user
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC")
    op.execute("GRANT INSERT, SELECT ON audit_log TO app_user")


def downgrade() -> None:
    op.drop_table('audit_log')
