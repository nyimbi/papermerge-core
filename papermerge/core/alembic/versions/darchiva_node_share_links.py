"""add node_share_links table

Revision ID: darchiva_node_share_links
Revises: darchiva_iam_invitations
Create Date: 2026-06-12 01:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'darchiva_node_share_links'
down_revision: Union[str, None] = 'darchiva_iam_invitations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		'node_share_links',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('node_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('created_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
		sa.Column('token', sa.String(), nullable=False, unique=True),
		sa.Column('permissions', postgresql.ARRAY(sa.String()), nullable=False, server_default='{}'),
		sa.Column('password_hash', sa.String(), nullable=True),
		sa.Column('expires_at', sa.DateTime(), nullable=True),
		sa.Column('max_access_count', sa.Integer(), nullable=True),
		sa.Column('access_count', sa.Integer(), nullable=False, server_default='0'),
		sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
	)
	op.create_index('ix_node_share_links_node_id', 'node_share_links', ['node_id'])
	op.create_index('ix_node_share_links_token', 'node_share_links', ['token'], unique=True)


def downgrade() -> None:
	op.drop_index('ix_node_share_links_token', table_name='node_share_links')
	op.drop_index('ix_node_share_links_node_id', table_name='node_share_links')
	op.drop_table('node_share_links')
