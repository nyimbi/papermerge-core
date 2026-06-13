"""Add user_passkeys and webauthn_challenges tables.

Revision ID: darchiva_webauthn_passkeys
Revises: darchiva_mfa_settings
Create Date: 2026-06-13
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "darchiva_webauthn_passkeys"
down_revision: Union[str, None] = "darchiva_mfa_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_passkeys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("credential_id", sa.LargeBinary, nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary, nullable=False),
        sa.Column("sign_count", sa.Integer, nullable=False, default=0),
        sa.Column("name", sa.String(255), nullable=False, default="Passkey"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "webauthn_challenges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("challenge", sa.LargeBinary, nullable=False),
        sa.Column("challenge_type", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("webauthn_challenges")
    op.drop_table("user_passkeys")
