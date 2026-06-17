"""Add legal_hold_entries table for named legal holds on documents.

Revision ID: darchiva_legal_hold
Revises: darchiva_dedup
Create Date: 2026-06-17
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "darchiva_legal_hold"
down_revision: Union[str, None] = "darchiva_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.create_table(
		"legal_hold_entries",
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column(
			"document_id",
			sa.String(36),
			sa.ForeignKey("documents.id", ondelete="CASCADE"),
			nullable=False,
			index=True,
		),
		sa.Column("hold_name", sa.String(255), nullable=False),
		sa.Column("hold_reason", sa.Text(), nullable=False),
		sa.Column("held_by_id", sa.String(36), nullable=False),
		sa.Column("released_by_id", sa.String(36), nullable=True),
		sa.Column(
			"held_at",
			sa.TIMESTAMP(timezone=True),
			nullable=False,
			server_default=sa.func.now(),
		),
		sa.Column("released_at", sa.TIMESTAMP(timezone=True), nullable=True),
		sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
	)
	op.create_index(
		"idx_legal_hold_entries_document_active",
		"legal_hold_entries",
		["document_id", "released_at"],
	)


def downgrade() -> None:
	op.drop_index("idx_legal_hold_entries_document_active", table_name="legal_hold_entries")
	op.drop_table("legal_hold_entries")
