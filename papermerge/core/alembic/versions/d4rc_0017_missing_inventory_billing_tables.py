"""Add physical_manifests, cloud_providers, reconciliation_resolutions;
backfill missing columns on document_provenance and provenance_events.

Revision ID: d4rc_0017
Revises: d4rc_0016
Create Date: 2026-06-11
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "d4rc_0017"
down_revision: Union[str, None] = "d4rc_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── physical_manifests ──────────────────────────────────────────────
    op.create_table(
        "physical_manifests",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("barcode", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location_path", sa.String(512), nullable=True),
        sa.Column("responsible_person", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("barcode"),
    )
    op.create_index("ix_physical_manifests_barcode", "physical_manifests", ["barcode"])
    op.create_index("ix_physical_manifests_tenant", "physical_manifests", ["tenant_id"])

    # ── cloud_providers ─────────────────────────────────────────────────
    op.create_table(
        "cloud_providers",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "provider_type",
            sa.Enum(
                "aws", "linode", "cloudflare", "digitalocean", "gcp", "azure", "custom",
                name="providertype",
            ),
            nullable=False,
        ),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("config", JSONB(), nullable=True),
        sa.Column("account_id", sa.String(100), nullable=True),
        sa.Column("region", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cloud_providers_tenant", "cloud_providers", ["tenant_id"])
    op.create_index("ix_cloud_providers_type", "cloud_providers", ["provider_type"])

    # ── reconciliation_resolutions ──────────────────────────────────────
    op.create_table(
        "reconciliation_resolutions",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("discrepancy_id", sa.String(255), nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_by_id", UUID(as_uuid=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconciliation_discrepancy", "reconciliation_resolutions", ["discrepancy_id"]
    )
    op.create_index(
        "ix_reconciliation_tenant", "reconciliation_resolutions", ["tenant_id"]
    )

    # ── document_provenance: add missing columns ────────────────────────
    # d4rc_0002 created this table with a minimal schema; the ORM grew substantially.
    op.add_column(
        "document_provenance",
        sa.Column("physical_manifest_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_doc_provenance_manifest",
        "document_provenance",
        "physical_manifests",
        ["physical_manifest_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("document_provenance", sa.Column("original_file_size", sa.Integer(), nullable=True))
    op.add_column("document_provenance", sa.Column("original_mime_type", sa.String(100), nullable=True))
    op.add_column("document_provenance", sa.Column("current_file_hash", sa.String(128), nullable=True))
    op.add_column("document_provenance", sa.Column("blake3_hash", sa.String(64), nullable=True))
    op.add_column("document_provenance", sa.Column("last_hash_verified_at", sa.DateTime(), nullable=True))
    op.add_column("document_provenance", sa.Column("physical_reference", sa.String(255), nullable=True))
    op.add_column("document_provenance", sa.Column("ingestion_source", sa.String(50), nullable=True))
    op.add_column("document_provenance", sa.Column("ingestion_timestamp", sa.DateTime(), nullable=True))
    op.add_column("document_provenance", sa.Column("ingestion_user_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_doc_provenance_ingestion_user",
        "document_provenance",
        "users",
        ["ingestion_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("document_provenance", sa.Column("scan_resolution_dpi", sa.Integer(), nullable=True))
    op.add_column("document_provenance", sa.Column("scan_color_mode", sa.String(50), nullable=True))
    op.add_column("document_provenance", sa.Column("original_page_count", sa.Integer(), nullable=True))
    op.add_column("document_provenance", sa.Column("current_page_count", sa.Integer(), nullable=True))
    op.add_column(
        "document_provenance",
        sa.Column(
            "verification_status",
            sa.Enum("pending", "verified", "failed", "disputed", name="verificationstatus"),
            nullable=True,
        ),
    )
    op.add_column("document_provenance", sa.Column("verified_at", sa.DateTime(), nullable=True))
    op.add_column("document_provenance", sa.Column("verified_by_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_doc_provenance_verified_by",
        "document_provenance",
        "users",
        ["verified_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("document_provenance", sa.Column("verification_notes", sa.Text(), nullable=True))
    op.add_column("document_provenance", sa.Column("digital_signature", sa.Text(), nullable=True))
    op.add_column("document_provenance", sa.Column("signature_algorithm", sa.String(50), nullable=True))
    op.add_column("document_provenance", sa.Column("signature_timestamp", sa.DateTime(), nullable=True))
    op.add_column("document_provenance", sa.Column("certificate_chain", JSONB(), nullable=True))
    op.add_column("document_provenance", sa.Column("is_duplicate", sa.Boolean(), nullable=True, server_default="false"))
    op.add_column("document_provenance", sa.Column("duplicate_of_id", sa.String(32), nullable=True))
    op.add_column("document_provenance", sa.Column("similarity_hash", sa.String(64), nullable=True))
    op.add_column("document_provenance", sa.Column("extra_data", JSONB(), nullable=True))
    op.add_column(
        "document_provenance",
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )
    op.add_column("document_provenance", sa.Column("tenant_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_doc_provenance_tenant",
        "document_provenance",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── provenance_events: add missing columns ──────────────────────────
    # d4rc_0002 created provenance_events with document_id FK; ORM was redesigned
    # to use provenance_id FK to document_provenance.id instead.
    op.add_column(
        "provenance_events",
        sa.Column("provenance_id", sa.String(32), nullable=True),
    )
    op.create_foreign_key(
        "fk_provenance_events_provenance",
        "provenance_events",
        "document_provenance",
        ["provenance_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column("provenance_events", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("provenance_events", sa.Column("previous_state", JSONB(), nullable=True))
    op.add_column("provenance_events", sa.Column("new_state", JSONB(), nullable=True))
    op.add_column("provenance_events", sa.Column("related_document_id", UUID(as_uuid=True), nullable=True))
    op.add_column("provenance_events", sa.Column("workflow_id", sa.String(32), nullable=True))
    op.add_column("provenance_events", sa.Column("workflow_step_id", sa.String(32), nullable=True))
    op.add_column("provenance_events", sa.Column("event_hash", sa.String(64), nullable=True))
    op.add_column("provenance_events", sa.Column("previous_event_hash", sa.String(64), nullable=True))
    # Rename actor_type from 20 → 50 chars to match ORM
    op.alter_column(
        "provenance_events",
        "actor_type",
        existing_type=sa.String(20),
        type_=sa.String(50),
        existing_nullable=True,
    )
    # event_type in migration is String(50); ORM uses Enum - add enum type
    op.add_column(
        "provenance_events",
        sa.Column(
            "timestamp",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    # provenance_events columns
    op.drop_column("provenance_events", "timestamp")
    op.alter_column("provenance_events", "actor_type", existing_type=sa.String(50), type_=sa.String(20))
    op.drop_column("provenance_events", "previous_event_hash")
    op.drop_column("provenance_events", "event_hash")
    op.drop_column("provenance_events", "workflow_step_id")
    op.drop_column("provenance_events", "workflow_id")
    op.drop_column("provenance_events", "related_document_id")
    op.drop_column("provenance_events", "new_state")
    op.drop_column("provenance_events", "previous_state")
    op.drop_column("provenance_events", "description")
    op.drop_constraint("fk_provenance_events_provenance", "provenance_events", type_="foreignkey")
    op.drop_column("provenance_events", "provenance_id")

    # document_provenance columns
    op.drop_constraint("fk_doc_provenance_tenant", "document_provenance", type_="foreignkey")
    op.drop_column("document_provenance", "tenant_id")
    op.drop_column("document_provenance", "updated_at")
    op.drop_column("document_provenance", "extra_data")
    op.drop_column("document_provenance", "similarity_hash")
    op.drop_column("document_provenance", "duplicate_of_id")
    op.drop_column("document_provenance", "is_duplicate")
    op.drop_column("document_provenance", "certificate_chain")
    op.drop_column("document_provenance", "signature_timestamp")
    op.drop_column("document_provenance", "signature_algorithm")
    op.drop_column("document_provenance", "digital_signature")
    op.drop_column("document_provenance", "verification_notes")
    op.drop_constraint("fk_doc_provenance_verified_by", "document_provenance", type_="foreignkey")
    op.drop_column("document_provenance", "verified_by_id")
    op.drop_column("document_provenance", "verified_at")
    op.drop_column("document_provenance", "verification_status")
    op.drop_column("document_provenance", "current_page_count")
    op.drop_column("document_provenance", "original_page_count")
    op.drop_column("document_provenance", "scan_color_mode")
    op.drop_column("document_provenance", "scan_resolution_dpi")
    op.drop_constraint("fk_doc_provenance_ingestion_user", "document_provenance", type_="foreignkey")
    op.drop_column("document_provenance", "ingestion_user_id")
    op.drop_column("document_provenance", "ingestion_timestamp")
    op.drop_column("document_provenance", "ingestion_source")
    op.drop_column("document_provenance", "physical_reference")
    op.drop_column("document_provenance", "last_hash_verified_at")
    op.drop_column("document_provenance", "blake3_hash")
    op.drop_column("document_provenance", "current_file_hash")
    op.drop_column("document_provenance", "original_mime_type")
    op.drop_column("document_provenance", "original_file_size")
    op.drop_constraint("fk_doc_provenance_manifest", "document_provenance", type_="foreignkey")
    op.drop_column("document_provenance", "physical_manifest_id")

    # new tables
    op.drop_table("reconciliation_resolutions")
    op.drop_table("cloud_providers")
    op.drop_table("physical_manifests")
