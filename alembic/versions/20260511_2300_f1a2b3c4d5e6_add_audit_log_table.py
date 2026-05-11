"""add_audit_log_table

Revision ID: f1a2b3c4d5e6
Revises:     e7f8a9b0c1d2
Create Date: 2026-05-11 23:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_role", sa.String(length=50), nullable=True),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"], unique=False)
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"], unique=False)
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;")
    op.execute("GRANT INSERT, SELECT ON audit_log TO app_user;")


def downgrade() -> None:
    op.drop_index("ix_audit_log_event_type", table_name="audit_log")
    op.drop_index("ix_audit_log_timestamp", table_name="audit_log")
    op.drop_table("audit_log")
