"""Add outbound_webhooks and webhook_deliveries tables.

Revision ID: darchiva_outbound_webhooks
Revises: darchiva_exception_supervisor_tables
Create Date: 2026-06-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "darchiva_outbound_webhooks"
down_revision = "darchiva_exception_supervisor_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── outbound_webhooks ────────────────────────────────────────────────────
    op.create_table(
        "outbound_webhooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("events", JSONB, nullable=False, server_default="'[]'::jsonb"),
        sa.Column("secret", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_status", sa.Integer, nullable=True),
    )
    op.create_index("ix_outbound_webhooks_tenant", "outbound_webhooks", ["tenant_id"])
    op.create_index(
        "ix_outbound_webhooks_active", "outbound_webhooks", ["tenant_id", "is_active"]
    )

    # ── webhook_deliveries ───────────────────────────────────────────────────
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "webhook_id",
            sa.String(36),
            sa.ForeignKey("outbound_webhooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="'{}'::jsonb"),
        sa.Column("response_status", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_webhook", "webhook_deliveries", ["webhook_id"]
    )
    op.create_index(
        "ix_webhook_deliveries_created", "webhook_deliveries", ["created_at"]
    )
    op.create_index(
        "ix_webhook_deliveries_event", "webhook_deliveries", ["event_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_event", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_created", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_webhook", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")

    op.drop_index("ix_outbound_webhooks_active", table_name="outbound_webhooks")
    op.drop_index("ix_outbound_webhooks_tenant", table_name="outbound_webhooks")
    op.drop_table("outbound_webhooks")
