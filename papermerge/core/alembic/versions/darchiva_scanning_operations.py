"""Add safety_checks and chain_of_custody tables for scanning operations.

Revision ID: darchiva_scanning_operations
Revises: darchiva_billing_tables
Create Date: 2026-06-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "darchiva_scanning_operations"
down_revision = "darchiva_billing_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_checks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operator_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operator_name", sa.String(255), nullable=False),
        sa.Column("has_gloves", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_mask", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_vest", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_shoes", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_feeling_well", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("temperature_check", sa.Float, nullable=True),
        sa.Column("check_date", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "verified_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_safety_checks_tenant", "safety_checks", ["tenant_id"])
    op.create_index("ix_safety_checks_operator", "safety_checks", ["operator_id"])
    op.create_index("ix_safety_checks_date", "safety_checks", ["check_date"])

    op.create_table(
        "chain_of_custody",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("scanning_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.Enum(
                "check_out", "transfer", "check_in", "scan_start", "scan_end", "return",
                name="custodyeventtype",
            ),
            nullable=False,
        ),
        sa.Column("timestamp", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "from_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_location", sa.String(255), nullable=True),
        sa.Column(
            "to_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("to_location", sa.String(255), nullable=True),
        sa.Column("signature_image_path", sa.String(512), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chain_of_custody_tenant", "chain_of_custody", ["tenant_id"])
    op.create_index("ix_chain_of_custody_batch", "chain_of_custody", ["batch_id"])
    op.create_index("ix_chain_of_custody_timestamp", "chain_of_custody", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_chain_of_custody_timestamp", table_name="chain_of_custody")
    op.drop_index("ix_chain_of_custody_batch", table_name="chain_of_custody")
    op.drop_index("ix_chain_of_custody_tenant", table_name="chain_of_custody")
    op.drop_table("chain_of_custody")
    op.drop_index("ix_safety_checks_date", table_name="safety_checks")
    op.drop_index("ix_safety_checks_operator", table_name="safety_checks")
    op.drop_index("ix_safety_checks_tenant", table_name="safety_checks")
    op.drop_table("safety_checks")
    op.execute("DROP TYPE IF EXISTS custodyeventtype")
