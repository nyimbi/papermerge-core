"""add user_invitations table

Revision ID: darchiva_iam_invitations
Revises: fa71c2c795a9
Create Date: 2026-06-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'darchiva_iam_invitations'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		'user_invitations',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('email', sa.String(), nullable=False),
		sa.Column('invited_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('status', sa.String(), nullable=False, server_default='pending'),
		sa.Column('token', sa.String(), nullable=False, unique=True),
		sa.Column('role_ids', postgresql.ARRAY(sa.String()), nullable=True),
		sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
		sa.Column('expires_at', sa.DateTime(), nullable=True),
		sa.Column('accepted_at', sa.DateTime(), nullable=True),
		sa.Column('last_sent_at', sa.DateTime(), nullable=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=True),
	)
	op.create_index('ix_user_invitations_email', 'user_invitations', ['email'])
	op.create_index('ix_user_invitations_status', 'user_invitations', ['status'])
	op.create_index('ix_user_invitations_token', 'user_invitations', ['token'], unique=True)


def downgrade() -> None:
	op.drop_index('ix_user_invitations_token', table_name='user_invitations')
	op.drop_index('ix_user_invitations_status', table_name='user_invitations')
	op.drop_index('ix_user_invitations_email', table_name='user_invitations')
	op.drop_table('user_invitations')
