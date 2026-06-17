"""add document_acls table for per-resource access control lists

Revision ID: darchiva_acl_001
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "darchiva_acl_001"
down_revision: Union[str, None] = "fa71c2c795a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		"document_acls",
		sa.Column(
			"id",
			postgresql.UUID(as_uuid=True),
			primary_key=True,
			nullable=False,
		),
		sa.Column("resource_type", sa.String(20), nullable=False),
		sa.Column("resource_id", sa.String(36), nullable=False),
		sa.Column("principal_type", sa.String(20), nullable=False),
		sa.Column("principal_id", sa.String(36), nullable=False),
		sa.Column("principal_name", sa.String(255), nullable=False),
		sa.Column("can_read", sa.Boolean(), nullable=False, server_default="true"),
		sa.Column("can_write", sa.Boolean(), nullable=False, server_default="false"),
		sa.Column("can_delete", sa.Boolean(), nullable=False, server_default="false"),
		sa.Column("can_share", sa.Boolean(), nullable=False, server_default="false"),
		sa.Column("granted_by_id", sa.String(36), nullable=False),
		sa.Column("tenant_id", sa.String(36), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			server_default=sa.text("now()"),
			nullable=False,
		),
		sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
		sa.CheckConstraint(
			"resource_type IN ('document', 'folder')",
			name="document_acls_resource_type_check",
		),
		sa.CheckConstraint(
			"principal_type IN ('user', 'group')",
			name="document_acls_principal_type_check",
		),
		sa.UniqueConstraint(
			"resource_type",
			"resource_id",
			"principal_type",
			"principal_id",
			name="uq_document_acls_resource_principal",
		),
	)

	op.create_index(
		"ix_document_acls_resource",
		"document_acls",
		["resource_type", "resource_id"],
	)
	op.create_index(
		"ix_document_acls_principal",
		"document_acls",
		["principal_type", "principal_id"],
	)
	op.create_index(
		"ix_document_acls_tenant",
		"document_acls",
		["tenant_id"],
	)


def downgrade() -> None:
	op.drop_index("ix_document_acls_tenant", table_name="document_acls")
	op.drop_index("ix_document_acls_principal", table_name="document_acls")
	op.drop_index("ix_document_acls_resource", table_name="document_acls")
	op.drop_table("document_acls")
