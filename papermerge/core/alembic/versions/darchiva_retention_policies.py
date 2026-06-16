"""dArchiva: document retention policies table

Revision ID: darchiva_retention_policies
Revises: darchiva_annotations, darchiva_batch_templates, darchiva_share_links
Create Date: 2026-06-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "darchiva_retention_policies"
down_revision: Union[tuple, None] = (
	"darchiva_annotations",
	"darchiva_batch_templates",
	"darchiva_share_links",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		"retention_policies",
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("name", sa.String(255), nullable=False),
		sa.Column("description", sa.Text(), nullable=True),
		sa.Column("policy_type", sa.String(20), nullable=False),
		sa.Column("after_days", sa.Integer(), nullable=False),
		sa.Column(
			"applies_to_project_id",
			sa.String(36),
			sa.ForeignKey("scanning_projects.id", ondelete="SET NULL"),
			nullable=True,
		),
		sa.Column("applies_to_document_type", sa.String(255), nullable=True),
		sa.Column("destination_folder_id", sa.String(36), nullable=True),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
		sa.Column(
			"tenant_id",
			sa.String(36),
			sa.ForeignKey("tenants.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column(
			"created_by_id",
			sa.String(36),
			sa.ForeignKey("users.id", ondelete="SET NULL"),
			nullable=True,
		),
		sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
		sa.Column("last_run_at", sa.DateTime(), nullable=True),
		sa.Column("docs_processed", sa.Integer(), nullable=False, server_default="0"),
	)
	op.create_index(
		"ix_retention_policies_tenant_active",
		"retention_policies",
		["tenant_id", "is_active"],
	)
	op.create_index(
		"ix_retention_policies_project",
		"retention_policies",
		["applies_to_project_id"],
	)


def downgrade() -> None:
	op.drop_index("ix_retention_policies_project", table_name="retention_policies")
	op.drop_index("ix_retention_policies_tenant_active", table_name="retention_policies")
	op.drop_table("retention_policies")
