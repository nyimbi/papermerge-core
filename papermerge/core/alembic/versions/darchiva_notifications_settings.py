"""Add notifications, notification_settings, system_settings, webhook_configs tables.

Revision ID: darchiva_notifications_settings
Revises: darchiva_merge_heads
Create Date: 2026-06-13
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID, ARRAY

revision: str = "darchiva_notifications_settings"
down_revision: Union[str, None] = "darchiva_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read"])

    op.create_table(
        "system_settings",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by_id", sa.Text, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )

    op.create_table(
        "webhook_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("events", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("secret", sa.Text, nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "notification_settings",
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("preferences", JSONB, nullable=False, server_default="{}"),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("notification_settings")
    op.drop_table("webhook_configs")
    op.drop_table("system_settings")
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_table("notifications")
