"""Add legal_hold and retention fields to documents.

Revision ID: darchiva_legal_holds
Revises: darchiva_scan_agents
Create Date: 2026-06-15
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "darchiva_legal_holds"
down_revision: Union[str, None] = "darchiva_scan_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.add_column(
		"documents",
		sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default="false"),
	)
	op.add_column(
		"documents",
		sa.Column("retention_date", sa.TIMESTAMP(timezone=True), nullable=True),
	)
	op.add_column(
		"documents",
		sa.Column("retention_policy", sa.String(100), nullable=True),
	)
	op.add_column(
		"documents",
		sa.Column("document_metadata", JSONB(), nullable=True),
	)
	op.create_index("idx_documents_legal_hold", "documents", ["legal_hold"])
	op.create_index("idx_documents_retention_date", "documents", ["retention_date"])


def downgrade() -> None:
	op.drop_index("idx_documents_retention_date", table_name="documents")
	op.drop_index("idx_documents_legal_hold", table_name="documents")
	op.drop_column("documents", "document_metadata")
	op.drop_column("documents", "retention_policy")
	op.drop_column("documents", "retention_date")
	op.drop_column("documents", "legal_hold")
