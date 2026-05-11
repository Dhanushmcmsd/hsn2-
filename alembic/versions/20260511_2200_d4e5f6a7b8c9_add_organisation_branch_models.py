"""add_organisation_branch_models

Revision ID: d4e5f6a7b8c9
Revises:     c9d8e7f6a5b4
Create Date: 2026-05-11 22:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c9d8e7f6a5b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

    op.create_table(
        "organisations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("gstin_prefix", sa.String(length=15), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_organisations_name", "organisations", ["name"], unique=False)

    op.create_table(
        "branches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "name", name="uq_branches_org_name"),
    )
    op.create_index("ix_branches_organisation_id", "branches", ["organisation_id"], unique=False)

    op.add_column("users", sa.Column("branch_id", sa.Uuid(), nullable=True))
    op.add_column("predictions", sa.Column("branch_id", sa.Uuid(), nullable=True))
    op.add_column("api_keys", sa.Column("branch_id", sa.Uuid(), nullable=True))

    op.create_foreign_key("fk_users_branch_id", "users", "branches", ["branch_id"], ["id"])
    op.create_foreign_key("fk_predictions_branch_id", "predictions", "branches", ["branch_id"], ["id"])
    op.create_foreign_key("fk_api_keys_branch_id", "api_keys", "branches", ["branch_id"], ["id"])

    op.create_index("idx_predictions_branch", "predictions", ["branch_id"], unique=False)
    op.create_index("idx_users_branch", "users", ["branch_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_users_branch", table_name="users")
    op.drop_index("idx_predictions_branch", table_name="predictions")
    op.drop_constraint("fk_api_keys_branch_id", "api_keys", type_="foreignkey")
    op.drop_constraint("fk_predictions_branch_id", "predictions", type_="foreignkey")
    op.drop_constraint("fk_users_branch_id", "users", type_="foreignkey")
    op.drop_column("api_keys", "branch_id")
    op.drop_column("predictions", "branch_id")
    op.drop_column("users", "branch_id")
    op.drop_index("ix_branches_organisation_id", table_name="branches")
    op.drop_table("branches")
    op.drop_index("ix_organisations_name", table_name="organisations")
    op.drop_table("organisations")
