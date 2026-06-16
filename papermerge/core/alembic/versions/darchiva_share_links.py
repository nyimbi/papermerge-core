"""Add document_share_links table for expiring public share links.

Revision ID: darchiva_share_links
Revises: darchiva_legal_holds
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "darchiva_share_links"
down_revision: Union[str, None] = "darchiva_legal_holds"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_share_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("max_views", sa.Integer(), nullable=True),
        sa.Column(
            "view_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_document_share_links_document_id",
        "document_share_links",
        ["document_id"],
    )
    op.create_index(
        "ix_document_share_links_token",
        "document_share_links",
        ["token"],
        unique=True,
    )
    op.create_index(
        "ix_document_share_links_tenant_id",
        "document_share_links",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_share_links_tenant_id", table_name="document_share_links")
    op.drop_index("ix_document_share_links_token", table_name="document_share_links")
    op.drop_index("ix_document_share_links_document_id", table_name="document_share_links")
    op.drop_table("document_share_links")
