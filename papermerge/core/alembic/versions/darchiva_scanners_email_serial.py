"""Add scanners, email, and serial-number tables.

Revision ID: darchiva_scanners_email_serial
Revises: darchiva_scanning_operations
Create Date: 2026-06-13

"""
from alembic import op
import sqlalchemy as sa

revision = "darchiva_scanners_email_serial"
down_revision = "darchiva_scanning_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Scanners ────────────────────────────────────────────────────────────
    op.create_table(
        "scanners",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("protocol", sa.String(20), nullable=False),
        sa.Column("connection_uri", sa.String(500), nullable=False),
        sa.Column("manufacturer", sa.String(255), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("serial_number", sa.String(100), nullable=True),
        sa.Column("firmware_version", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="offline"),
        sa.Column("last_seen_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("location_id", sa.String(36), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("api_key_hash", sa.String(128), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("capabilities", sa.JSON, nullable=True),
        sa.Column("total_pages_scanned", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_jobs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_scanners_tenant", "scanners", ["tenant_id"])
    op.create_index("ix_scanners_api_key_hash", "scanners", ["api_key_hash"])

    op.create_table(
        "scan_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("options", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_scan_profiles_tenant", "scan_profiles", ["tenant_id"])

    op.create_table(
        "scanner_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("auto_discovery_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("discovery_interval_seconds", sa.Integer, nullable=False, server_default="300"),
        sa.Column("default_profile_id", sa.String(36), nullable=True),
        sa.Column("auto_process_scans", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("default_destination_folder_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scanner_id", sa.String(36), sa.ForeignKey("scanners.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("options", sa.JSON, nullable=True),
        sa.Column("pages_scanned", sa.Integer, nullable=False, server_default="0"),
        sa.Column("scan_time_ms", sa.Float, nullable=True),
        sa.Column("document_ids", sa.JSON, nullable=True),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column("physical_manifest_id", sa.String(36), nullable=True),
        sa.Column("destination_folder_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_scan_jobs_tenant", "scan_jobs", ["tenant_id"])
    op.create_index("ix_scan_jobs_scanner", "scan_jobs", ["scanner_id"])
    op.create_index("ix_scan_jobs_user", "scan_jobs", ["user_id"])
    op.create_index("ix_scan_jobs_status", "scan_jobs", ["status"])

    # ── Serial Numbers ───────────────────────────────────────────────────────
    op.create_table(
        "serial_number_sequences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("pattern", sa.String(200), nullable=False, server_default="{PREFIX}-{YEAR}{MONTH}-{SEQ:5}"),
        sa.Column("prefix", sa.String(20), nullable=False, server_default="DOC"),
        sa.Column("current_value", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reset_frequency", sa.String(20), nullable=False, server_default="yearly"),
        sa.Column("last_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_type_id", sa.String(36), sa.ForeignKey("document_types.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("auto_assign", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("allow_manual", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.String(36), nullable=True),
        sa.UniqueConstraint("document_type_id", "tenant_id", name="uq_sequence_doctype_tenant"),
    )
    op.create_index("ix_serial_sequence_doctype", "serial_number_sequences", ["document_type_id"])
    op.create_index("ix_serial_sequence_tenant", "serial_number_sequences", ["tenant_id"])

    op.create_table(
        "document_serial_numbers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("serial_number", sa.String(100), nullable=False),
        sa.Column("sequence_id", sa.String(36), sa.ForeignKey("serial_number_sequences.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sequence_value", sa.Integer, nullable=True),
        sa.Column("is_manual", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("assigned_by_id", sa.String(36), nullable=True),
        sa.UniqueConstraint("serial_number", "tenant_id", name="uq_serial_number_tenant"),
    )
    op.create_index("ix_doc_serial_number", "document_serial_numbers", ["serial_number"])
    op.create_index("ix_doc_serial_tenant", "document_serial_numbers", ["tenant_id"])

    # ── Emails ───────────────────────────────────────────────────────────────
    op.create_table(
        "email_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(50), nullable=False),
        sa.Column("email_address", sa.String(500), nullable=False),
        sa.Column("imap_host", sa.String(255), nullable=True),
        sa.Column("imap_port", sa.Integer, nullable=True),
        sa.Column("imap_use_ssl", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("imap_username", sa.String(255), nullable=True),
        sa.Column("imap_password_encrypted", sa.Text, nullable=True),
        sa.Column("oauth_provider", sa.String(50), nullable=True),
        sa.Column("oauth_tenant_id", sa.String(100), nullable=True),
        sa.Column("oauth_client_id", sa.String(255), nullable=True),
        sa.Column("oauth_client_secret_encrypted", sa.Text, nullable=True),
        sa.Column("oauth_refresh_token_encrypted", sa.Text, nullable=True),
        sa.Column("oauth_access_token_encrypted", sa.Text, nullable=True),
        sa.Column("oauth_token_expires", sa.DateTime, nullable=True),
        sa.Column("sync_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sync_folders", sa.JSON, nullable=True),
        sa.Column("sync_since_date", sa.DateTime, nullable=True),
        sa.Column("last_sync_at", sa.DateTime, nullable=True),
        sa.Column("last_sync_uid", sa.String(100), nullable=True),
        sa.Column("sync_interval_minutes", sa.Integer, nullable=False, server_default="15"),
        sa.Column("target_folder_id", sa.String(36), sa.ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("auto_process", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("import_attachments", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("attachment_filter", sa.JSON, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("connection_status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("connection_error", sa.Text, nullable=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "email_threads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("thread_id", sa.String(255), nullable=False, unique=True),
        sa.Column("subject", sa.String(1000), nullable=False),
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_message_date", sa.DateTime, nullable=True),
        sa.Column("last_message_date", sa.DateTime, nullable=True),
        sa.Column("participants", sa.JSON, nullable=True),
        sa.Column("folder_id", sa.String(36), sa.ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_email_threads_thread_id", "email_threads", ["thread_id"])
    op.create_index("ix_email_threads_owner", "email_threads", ["owner_id"])

    op.create_table(
        "email_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(512), nullable=False, unique=True),
        sa.Column("thread_id", sa.String(36), sa.ForeignKey("email_threads.id"), nullable=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.node_id"), nullable=True),
        sa.Column("subject", sa.String(1000), nullable=True),
        sa.Column("from_address", sa.String(500), nullable=False),
        sa.Column("from_name", sa.String(255), nullable=True),
        sa.Column("to_addresses", sa.JSON, nullable=True),
        sa.Column("cc_addresses", sa.JSON, nullable=True),
        sa.Column("bcc_addresses", sa.JSON, nullable=True),
        sa.Column("reply_to", sa.String(500), nullable=True),
        sa.Column("in_reply_to", sa.String(512), nullable=True),
        sa.Column("references", sa.JSON, nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("body_html", sa.Text, nullable=True),
        sa.Column("has_attachments", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("attachment_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sent_date", sa.DateTime, nullable=True),
        sa.Column("received_date", sa.DateTime, nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_account_id", sa.String(36), sa.ForeignKey("email_accounts.id"), nullable=True),
        sa.Column("raw_headers", sa.JSON, nullable=True),
        sa.Column("import_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("import_error", sa.Text, nullable=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("folder_id", sa.String(36), sa.ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_email_imports_message_id", "email_imports", ["message_id"])
    op.create_index("ix_email_imports_status", "email_imports", ["import_status"])

    op.create_table(
        "email_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email_import_id", sa.String(36), sa.ForeignKey("email_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.node_id"), nullable=True),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("content_id", sa.String(255), nullable=True),
        sa.Column("is_inline", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("import_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("import_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_email_attachments_import", "email_attachments", ["email_import_id"])

    op.create_table(
        "email_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("email_accounts.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("conditions", sa.JSON, nullable=True),
        sa.Column("actions", sa.JSON, nullable=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_email_accounts_owner", "email_accounts", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_email_accounts_owner", table_name="email_accounts")
    op.drop_table("email_rules")
    op.drop_index("ix_email_attachments_import", table_name="email_attachments")
    op.drop_table("email_attachments")
    op.drop_index("ix_email_imports_status", table_name="email_imports")
    op.drop_index("ix_email_imports_message_id", table_name="email_imports")
    op.drop_table("email_imports")
    op.drop_index("ix_email_threads_owner", table_name="email_threads")
    op.drop_index("ix_email_threads_thread_id", table_name="email_threads")
    op.drop_table("email_threads")
    op.drop_table("email_accounts")

    op.drop_index("ix_doc_serial_tenant", table_name="document_serial_numbers")
    op.drop_index("ix_doc_serial_number", table_name="document_serial_numbers")
    op.drop_table("document_serial_numbers")
    op.drop_index("ix_serial_sequence_tenant", table_name="serial_number_sequences")
    op.drop_index("ix_serial_sequence_doctype", table_name="serial_number_sequences")
    op.drop_table("serial_number_sequences")

    op.drop_index("ix_scan_jobs_status", table_name="scan_jobs")
    op.drop_index("ix_scan_jobs_user", table_name="scan_jobs")
    op.drop_index("ix_scan_jobs_scanner", table_name="scan_jobs")
    op.drop_index("ix_scan_jobs_tenant", table_name="scan_jobs")
    op.drop_table("scan_jobs")
    op.drop_table("scanner_settings")
    op.drop_index("ix_scan_profiles_tenant", table_name="scan_profiles")
    op.drop_table("scan_profiles")
    op.drop_index("ix_scanners_api_key_hash", table_name="scanners")
    op.drop_index("ix_scanners_tenant", table_name="scanners")
    op.drop_table("scanners")
