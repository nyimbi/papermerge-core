"""dArchiva: document annotations table

Revision ID: darchiva_annotations
Revises: darchiva_legal_holds, darchiva_outbound_webhooks, darchiva_dedup_quality_config
Create Date: 2026-06-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "darchiva_annotations"
down_revision: Union[tuple, None] = (
	"darchiva_legal_holds",
	"darchiva_outbound_webhooks",
	"darchiva_dedup_quality_config",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		"document_annotations",
		sa.Column(
			"id",
			sa.UUID(),
			server_default=sa.text("gen_random_uuid()"),
			nullable=False,
		),
		sa.Column("document_id", sa.UUID(), nullable=False),
		sa.Column("page_number", sa.Integer(), nullable=False),
		sa.Column("annotation_type", sa.String(32), nullable=False),
		sa.Column("x", sa.Float(), nullable=False),
		sa.Column("y", sa.Float(), nullable=False),
		sa.Column("width", sa.Float(), nullable=False),
		sa.Column("height", sa.Float(), nullable=False),
		sa.Column("content", sa.Text(), nullable=True),
		sa.Column("color", sa.String(32), nullable=False, server_default="#FFD700"),
		sa.Column("created_by_id", sa.String(64), nullable=False),
		sa.Column("tenant_id", sa.String(64), nullable=False),
		sa.Column(
			"created_at",
			sa.TIMESTAMP(timezone=True),
			server_default=sa.text("now()"),
			nullable=False,
		),
		sa.Column(
			"updated_at",
			sa.TIMESTAMP(timezone=True),
			server_default=sa.text("now()"),
			nullable=False,
		),
		sa.ForeignKeyConstraint(
			["document_id"],
			["documents.id"],
			ondelete="CASCADE",
		),
		sa.PrimaryKeyConstraint("id"),
	)
	op.create_index(
		"idx_annotation_document_page",
		"document_annotations",
		["document_id", "page_number"],
	)
	op.create_index(
		"idx_annotation_tenant",
		"document_annotations",
		["tenant_id"],
	)
	op.create_index(
		"idx_annotation_created_by",
		"document_annotations",
		["created_by_id"],
	)


def downgrade() -> None:
	op.drop_index("idx_annotation_created_by", table_name="document_annotations")
	op.drop_index("idx_annotation_tenant", table_name="document_annotations")
	op.drop_index("idx_annotation_document_page", table_name="document_annotations")
	op.drop_table("document_annotations")
