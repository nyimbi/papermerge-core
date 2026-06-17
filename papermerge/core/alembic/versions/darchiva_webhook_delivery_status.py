"""Add status, attempts, last_attempt_at columns to webhook_deliveries.

Revision ID: darchiva_webhook_delivery_status
Revises: darchiva_outbound_webhooks
Create Date: 2026-06-17

"""
from alembic import op
import sqlalchemy as sa

revision = "darchiva_webhook_delivery_status"
down_revision = "darchiva_outbound_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column(
            "attempts",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column(
            "last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_status",
        "webhook_deliveries",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_status", table_name="webhook_deliveries")
    op.drop_column("webhook_deliveries", "last_attempt_at")
    op.drop_column("webhook_deliveries", "attempts")
    op.drop_column("webhook_deliveries", "status")
