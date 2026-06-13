"""Add user_sessions table for login session tracking.

Revision ID: darchiva_user_sessions
Revises: darchiva_saved_searches
Create Date: 2026-06-13
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "darchiva_user_sessions"
down_revision: Union[str, None] = "darchiva_saved_searches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("revoked", sa.Boolean, nullable=False, default=False),
    )


def downgrade() -> None:
    op.drop_table("user_sessions")
