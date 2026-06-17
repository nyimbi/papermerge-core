"""smart duplicate detection — document_hashes table

Revision ID: darchiva_dedup
Revises: a1b2c3d4e5f6
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "darchiva_dedup"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_hashes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("perceptual_hash", sa.String(64), nullable=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
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
            ["documents.node_id"],
            ondelete="CASCADE",
            name="fk_document_hashes_document_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_hashes"),
        sa.UniqueConstraint("document_id", name="uq_document_hashes_document_id"),
    )

    op.create_index(
        "ix_document_hashes_file_hash",
        "document_hashes",
        ["file_hash"],
    )
    op.create_index(
        "ix_document_hashes_content_hash",
        "document_hashes",
        ["content_hash"],
    )
    op.create_index(
        "ix_document_hashes_document_id",
        "document_hashes",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_hashes_document_id", table_name="document_hashes")
    op.drop_index("ix_document_hashes_content_hash", table_name="document_hashes")
    op.drop_index("ix_document_hashes_file_hash", table_name="document_hashes")
    op.drop_table("document_hashes")
