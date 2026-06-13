"""Add scan_agents table for agent fleet management.

Revision ID: darchiva_scan_agents
Revises: darchiva_user_sessions
Create Date: 2026-06-13
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "darchiva_scan_agents"
down_revision: Union[str, None] = "darchiva_user_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.create_table(
		"scan_agents",
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("name", sa.String(255), nullable=False, server_default=""),
		sa.Column("hostname", sa.String(255), nullable=False),
		sa.Column("platform", sa.String(32), nullable=False),
		sa.Column("version", sa.String(64), nullable=False, server_default=""),
		sa.Column("port", sa.Integer, nullable=False, server_default="7780"),
		sa.Column("ip_address", sa.String(64), nullable=True),
		sa.Column("pushed_config", postgresql.JSONB, nullable=True),
		sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
		sa.Column(
			"created_at",
			sa.DateTime(timezone=True),
			server_default=sa.text("now()"),
			nullable=False,
		),
		sa.Column(
			"updated_at",
			sa.DateTime(timezone=True),
			server_default=sa.text("now()"),
			nullable=False,
		),
	)
	op.create_index("ix_scan_agents_tenant_id", "scan_agents", ["tenant_id"])
	op.create_index("ix_scan_agents_hostname", "scan_agents", ["tenant_id", "hostname"])


def downgrade() -> None:
	op.drop_index("ix_scan_agents_hostname", "scan_agents")
	op.drop_index("ix_scan_agents_tenant_id", "scan_agents")
	op.drop_table("scan_agents")
