"""Add batch_templates table for reusable scan configs.

Revision ID: darchiva_batch_templates
Revises: darchiva_batch_priority
Create Date: 2026-06-17

"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "darchiva_batch_templates"
down_revision: Union[str, None] = "darchiva_batch_priority"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.create_table(
		"batch_templates",
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("name", sa.String(255), nullable=False),
		sa.Column("description", sa.String(2000), nullable=True),
		sa.Column("dpi", sa.Integer, nullable=False, server_default="300"),
		sa.Column("color_mode", sa.String(20), nullable=False, server_default="color"),
		sa.Column("paper_size", sa.String(20), nullable=False, server_default="A4"),
		sa.Column("quality_threshold", sa.Float, nullable=False, server_default="60.0"),
		sa.Column("barcode_enabled", sa.Boolean, nullable=False, server_default="false"),
		sa.Column("auto_deskew", sa.Boolean, nullable=False, server_default="true"),
		sa.Column("auto_enhance", sa.Boolean, nullable=False, server_default="false"),
		sa.Column("expected_pages_per_document", sa.Integer, nullable=True),
		sa.Column("notes_template", sa.String(2000), nullable=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("created_by_id", sa.String(36), nullable=False),
		sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
		sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
		sa.Column("usage_count", sa.Integer, nullable=False, server_default="0"),
	)
	op.create_index("ix_batch_templates_tenant_id", "batch_templates", ["tenant_id"])
	op.create_unique_constraint(
		"uq_batch_templates_tenant_name",
		"batch_templates",
		["tenant_id", "name"],
	)


def downgrade() -> None:
	op.drop_constraint("uq_batch_templates_tenant_name", "batch_templates", type_="unique")
	op.drop_index("ix_batch_templates_tenant_id", table_name="batch_templates")
	op.drop_table("batch_templates")
