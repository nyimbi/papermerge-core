"""Add document_fingerprints table and quality_config column to scanning_projects.

Revision ID: darchiva_dedup_quality_config
Revises: darchiva_exception_supervisor_tables
Create Date: 2026-06-13

"""
from alembic import op
import sqlalchemy as sa

revision = "darchiva_dedup_quality_config"
down_revision = "darchiva_exception_supervisor_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Document Fingerprints (SHA-256 + pHash dedup) ────────────────────────
    op.create_table(
        "document_fingerprints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("scanning_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("phash", sa.String(32), nullable=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("sha256", "tenant_id", name="uq_fingerprint_sha256_tenant"),
    )
    op.create_index("ix_fingerprint_sha256", "document_fingerprints", ["sha256"])
    op.create_index("ix_fingerprint_phash", "document_fingerprints", ["phash"])
    op.create_index("ix_fingerprint_doc", "document_fingerprints", ["document_id"])
    op.create_index("ix_fingerprint_tenant", "document_fingerprints", ["tenant_id"])

    # ── Quality Config on Scanning Projects ──────────────────────────────────
    op.add_column(
        "scanning_projects",
        sa.Column("quality_config", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scanning_projects", "quality_config")

    op.drop_index("ix_fingerprint_tenant", table_name="document_fingerprints")
    op.drop_index("ix_fingerprint_doc", table_name="document_fingerprints")
    op.drop_index("ix_fingerprint_phash", table_name="document_fingerprints")
    op.drop_index("ix_fingerprint_sha256", table_name="document_fingerprints")
    op.drop_table("document_fingerprints")
