"""dArchiva custom fields — project-scoped metadata schema

Revision ID: darchiva_custom_fields_001
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

Adds project-scoped columns to the existing custom_fields table and
creates a simplified custom_field_values_v2 table for the dArchiva UI.
The original custom_field_values table (JSONB-based computed columns) is
left intact; the v2 table uses plain nullable typed columns for simpler
read/write from the frontend.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "darchiva_custom_fields_001"
down_revision: Union[str, None] = "fa71c2c795a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Extend existing custom_fields with project-scope columns
    # ------------------------------------------------------------------
    op.add_column(
        "custom_fields",
        sa.Column("label", sa.String(255), nullable=True),
    )
    op.add_column(
        "custom_fields",
        sa.Column(
            "field_type",
            sa.String(50),
            nullable=False,
            server_default="text",
        ),
    )
    op.add_column(
        "custom_fields",
        sa.Column(
            "required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "custom_fields",
        sa.Column("options_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "custom_fields",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scanning_projects.id", ondelete="CASCADE", deferrable=True, initially="DEFERRED"),
            nullable=True,
        ),
    )
    op.add_column(
        "custom_fields",
        sa.Column(
            "is_global",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "custom_fields",
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "custom_fields",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # Populate field_type from existing type_handler for backwards compat
    op.execute(
        "UPDATE custom_fields SET field_type = type_handler WHERE field_type = 'text' AND type_handler IS NOT NULL"
    )

    op.create_index(
        "idx_custom_fields_project_id",
        "custom_fields",
        ["project_id"],
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )
    op.create_index(
        "idx_custom_fields_is_global",
        "custom_fields",
        ["is_global"],
    )
    op.create_index(
        "idx_custom_fields_tenant_id",
        "custom_fields",
        ["tenant_id"],
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 2. Create custom_field_values_v2 — plain typed columns, no Computed
    # ------------------------------------------------------------------
    op.create_table(
        "custom_field_values_v2",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.node_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("custom_fields.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Numeric(20, 6), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_index(
        "idx_cfv2_doc_field_unique",
        "custom_field_values_v2",
        ["document_id", "field_id"],
        unique=True,
    )
    op.create_index("idx_cfv2_doc", "custom_field_values_v2", ["document_id"])
    op.create_index("idx_cfv2_field", "custom_field_values_v2", ["field_id"])


def downgrade() -> None:
    op.drop_table("custom_field_values_v2")

    op.drop_index("idx_custom_fields_tenant_id", table_name="custom_fields")
    op.drop_index("idx_custom_fields_is_global", table_name="custom_fields")
    op.drop_index("idx_custom_fields_project_id", table_name="custom_fields")

    for col in ("tenant_id", "sort_order", "is_global", "project_id", "options_json", "required", "field_type", "label"):
        op.drop_column("custom_fields", col)
