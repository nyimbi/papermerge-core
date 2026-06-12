"""add user_mfa_settings table

Revision ID: darchiva_mfa_settings
Revises: darchiva_node_share_links
Create Date: 2026-06-12 02:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'darchiva_mfa_settings'
down_revision: Union[str, None] = 'darchiva_node_share_links'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		'user_mfa_settings',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
		sa.Column('totp_secret', sa.String(), nullable=True),
		sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default='false'),
		sa.Column('backup_codes', postgresql.ARRAY(sa.String()), nullable=True),
		sa.Column('backup_codes_generated_at', sa.DateTime(), nullable=True),
		sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
		sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
	)
	op.create_index('ix_user_mfa_settings_user_id', 'user_mfa_settings', ['user_id'], unique=True)


def downgrade() -> None:
	op.drop_index('ix_user_mfa_settings_user_id', table_name='user_mfa_settings')
	op.drop_table('user_mfa_settings')
