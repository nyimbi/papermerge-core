"""Add exception events, routing rules, and page scan event tables.

Revision ID: darchiva_exception_supervisor_tables
Revises: darchiva_scanners_email_serial
Create Date: 2026-06-13

"""
from alembic import op
import sqlalchemy as sa

revision = "darchiva_exception_supervisor_tables"
down_revision = "darchiva_scanners_email_serial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Exception Events ─────────────────────────────────────────────────────
    op.create_table(
        "exception_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scan_job_id", sa.String(36), sa.ForeignKey("scan_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("scanning_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("exception_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("routing_action", sa.String(50), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("auto_fixable", sa.Boolean, nullable=True, server_default="false"),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("defects", sa.JSON, nullable=True),
        sa.Column("resolved_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_exception_tenant", "exception_events", ["tenant_id"])
    op.create_index("ix_exception_status", "exception_events", ["status"])
    op.create_index("ix_exception_type", "exception_events", ["exception_type"])
    op.create_index("ix_exception_created", "exception_events", ["created_at"])

    # ── Exception Routing Rules ──────────────────────────────────────────────
    op.create_table(
        "exception_routing_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("scanning_projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("exception_type", sa.String(50), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_exc_rule_tenant", "exception_routing_rules", ["tenant_id"])
    op.create_index("ix_exc_rule_type", "exception_routing_rules", ["exception_type"])

    # ── Page Scan Events ─────────────────────────────────────────────────────
    op.create_table(
        "page_scan_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scan_job_id", sa.String(36), sa.ForeignKey("scan_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("scanning_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operator_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("scanning_projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("shift_assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("defects", sa.JSON, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_page_event_operator", "page_scan_events", ["operator_id"])
    op.create_index("ix_page_event_project", "page_scan_events", ["project_id"])
    op.create_index("ix_page_event_occurred", "page_scan_events", ["occurred_at"])
    op.create_index("ix_page_event_batch", "page_scan_events", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_page_event_batch", table_name="page_scan_events")
    op.drop_index("ix_page_event_occurred", table_name="page_scan_events")
    op.drop_index("ix_page_event_project", table_name="page_scan_events")
    op.drop_index("ix_page_event_operator", table_name="page_scan_events")
    op.drop_table("page_scan_events")

    op.drop_index("ix_exc_rule_type", table_name="exception_routing_rules")
    op.drop_index("ix_exc_rule_tenant", table_name="exception_routing_rules")
    op.drop_table("exception_routing_rules")

    op.drop_index("ix_exception_created", table_name="exception_events")
    op.drop_index("ix_exception_type", table_name="exception_events")
    op.drop_index("ix_exception_status", table_name="exception_events")
    op.drop_index("ix_exception_tenant", table_name="exception_events")
    op.drop_table("exception_events")
