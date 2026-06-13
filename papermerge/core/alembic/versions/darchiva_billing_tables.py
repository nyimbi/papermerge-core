"""Add pricing_tiers, usage_daily, usage_alerts, invoices, invoice_line_items tables.

cloud_providers already exists from d4rc_0017.

Revision ID: darchiva_billing_tables
Revises: darchiva_notifications_settings
Create Date: 2026-06-13
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "darchiva_billing_tables"
down_revision: Union[str, None] = "darchiva_notifications_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pricing_tiers",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider_id", sa.String(32), sa.ForeignKey("cloud_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("unit_price_cents", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("unit_name", sa.String(50), nullable=False, server_default="unit"),
        sa.Column("min_units", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("max_units", sa.BigInteger, nullable=True),
        sa.Column("free_tier_units", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("effective_from", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.UniqueConstraint("provider_id", "service", "min_units", name="uq_pricing_tier_provider_service_min"),
    )
    op.create_index("ix_pricing_tiers_provider", "pricing_tiers", ["provider_id"])
    op.create_index("ix_pricing_tiers_service", "pricing_tiers", ["service"])

    op.create_table(
        "usage_daily",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usage_date", sa.Date, nullable=False),
        sa.Column("storage_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("storage_hot_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("storage_cold_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("storage_archive_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("transfer_in_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("transfer_out_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("documents_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("documents_added", sa.Integer, nullable=False, server_default="0"),
        sa.Column("documents_deleted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pages_processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("api_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("search_queries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("active_users", sa.Integer, nullable=False, server_default="0"),
        sa.Column("storage_cost_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("transfer_cost_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("compute_cost_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_total_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_breakdown", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "usage_date", name="uq_usage_daily_tenant_date"),
    )
    op.create_index("ix_usage_daily_tenant", "usage_daily", ["tenant_id"])
    op.create_index("ix_usage_daily_date", "usage_daily", ["usage_date"])

    op.create_table(
        "usage_alerts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("threshold_value", sa.Numeric(16, 4), nullable=False),
        sa.Column("threshold_unit", sa.String(50), nullable=False),
        sa.Column("current_value", sa.Numeric(16, 4), nullable=False, server_default="0"),
        sa.Column("percentage_used", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("notify_at_percentage", JSONB, nullable=False, server_default="[]"),
        sa.Column("notifications_sent", JSONB, nullable=False, server_default="[]"),
        sa.Column("notification_channels", JSONB, nullable=False, server_default="[]"),
        sa.Column("last_triggered_at", sa.DateTime, nullable=True),
        sa.Column("triggered_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_usage_alerts_tenant", "usage_alerts", ["tenant_id"])
    op.create_index("ix_usage_alerts_type", "usage_alerts", ["alert_type"])
    op.create_index("ix_usage_alerts_status", "usage_alerts", ["status"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_number", sa.String(50), nullable=False, unique=True),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("subtotal_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("discount_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tax_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paid_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("balance_due_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("billing_name", sa.String(200), nullable=True),
        sa.Column("billing_email", sa.String(200), nullable=True),
        sa.Column("billing_address", JSONB, nullable=True),
        sa.Column("payment_method", sa.String(50), nullable=True),
        sa.Column("payment_id", sa.String(100), nullable=True),
        sa.Column("paid_at", sa.DateTime, nullable=True),
        sa.Column("issued_at", sa.DateTime, nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("internal_notes", sa.Text, nullable=True),
        sa.Column("pdf_path", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_invoices_tenant", "invoices", ["tenant_id"])
    op.create_index("ix_invoices_status", "invoices", ["status"])
    op.create_index("ix_invoices_period", "invoices", ["period_start", "period_end"])

    op.create_table(
        "invoice_line_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("invoice_id", sa.String(32), sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_number", sa.Integer, nullable=False, server_default="0"),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("service_type", sa.String(30), nullable=True),
        sa.Column("quantity", sa.Numeric(16, 4), nullable=False, server_default="1"),
        sa.Column("unit_name", sa.String(50), nullable=False, server_default="unit"),
        sa.Column("unit_price_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("subtotal_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("discount_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tax_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("tax_code", sa.String(50), nullable=True),
        sa.Column("extra_data", JSONB, nullable=True),
    )
    op.create_index("ix_invoice_line_items_invoice", "invoice_line_items", ["invoice_id"])


def downgrade() -> None:
    op.drop_index("ix_invoice_line_items_invoice", table_name="invoice_line_items")
    op.drop_table("invoice_line_items")
    op.drop_index("ix_invoices_period", table_name="invoices")
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_tenant", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_usage_alerts_status", table_name="usage_alerts")
    op.drop_index("ix_usage_alerts_type", table_name="usage_alerts")
    op.drop_index("ix_usage_alerts_tenant", table_name="usage_alerts")
    op.drop_table("usage_alerts")
    op.drop_index("ix_usage_daily_date", table_name="usage_daily")
    op.drop_index("ix_usage_daily_tenant", table_name="usage_daily")
    op.drop_table("usage_daily")
    op.drop_index("ix_pricing_tiers_service", table_name="pricing_tiers")
    op.drop_index("ix_pricing_tiers_provider", table_name="pricing_tiers")
    op.drop_table("pricing_tiers")
