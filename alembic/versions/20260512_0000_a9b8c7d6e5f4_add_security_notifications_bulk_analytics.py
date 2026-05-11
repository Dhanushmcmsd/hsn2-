"""add_security_notifications_bulk_analytics

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-05-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "a9b8c7d6e5f4"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("role", sa.String(length=50), nullable=False, server_default="branch_user"))
    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("rotation_reminder_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("secret", sa.String(length=128), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_webhook_endpoints_org_id", "webhook_endpoints", ["org_id"], unique=False)

    op.create_table(
        "bulk_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_bulk_imports_branch_id", "bulk_imports", ["branch_id"], unique=False)
    op.create_index("idx_bulk_imports_user_id", "bulk_imports", ["user_id"], unique=False)

    op.create_index("idx_predictions_created_at", "predictions", ["created_at"], unique=False)
    op.create_index("idx_predictions_branch_created", "predictions", ["branch_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_predictions_branch_created", table_name="predictions")
    op.drop_index("idx_predictions_created_at", table_name="predictions")

    op.drop_index("idx_bulk_imports_user_id", table_name="bulk_imports")
    op.drop_index("idx_bulk_imports_branch_id", table_name="bulk_imports")
    op.drop_table("bulk_imports")

    op.drop_index("idx_webhook_endpoints_org_id", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")

    op.drop_column("api_keys", "rotation_reminder_sent")
    op.drop_column("api_keys", "last_used_at")
    op.drop_column("api_keys", "expires_at")
    op.drop_column("api_keys", "role")
