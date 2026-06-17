"""Add connector_configs table for external connector imports.

Revision ID: darchiva_connectors
Revises: darchiva_webhook_delivery_status
Create Date: 2026-06-17

"""
from alembic import op
import sqlalchemy as sa

revision = "darchiva_connectors"
down_revision = "darchiva_webhook_delivery_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_configs",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("connector_type", sa.String(64), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("watch_folder_id", sa.String(1024), nullable=True),
        sa.Column("watch_folder_name", sa.String(512), nullable=True),
        sa.Column("destination_folder_id", sa.String(64), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_file_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "sync_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("created_by_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default="now()",
        ),
    )
    op.create_index(
        "ix_connector_configs_tenant_id",
        "connector_configs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_connector_configs_is_active",
        "connector_configs",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_configs_is_active", table_name="connector_configs")
    op.drop_index("ix_connector_configs_tenant_id", table_name="connector_configs")
    op.drop_table("connector_configs")
