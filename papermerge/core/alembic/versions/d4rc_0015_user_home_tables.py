# (c) Copyright Datacraft, 2026
"""Add user_home tables: notifications, favorites, search history.

Revision ID: d4rc_0015
Revises: d4rc_0014
Create Date: 2026-06-11

Three tables enabling real database persistence for the user home feature:
- user_notifications: per-user notification inbox with read tracking
- user_favorites: pinned documents/folders/searches/workflows
- user_search_history: recent search queries with filters and result counts
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0015'
down_revision: Union[str, None] = 'd4rc_0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# user_notifications — per-user notification inbox
	op.create_table(
		'user_notifications',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column(
			'user_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('users.id', ondelete='CASCADE'),
			nullable=False, index=True,
		),
		sa.Column('tenant_id', sa.String(255), nullable=True),
		sa.Column('type', sa.String(32), nullable=False),
		sa.Column('title', sa.Text, nullable=False),
		sa.Column('message', sa.Text, nullable=False),
		sa.Column('is_read', sa.Boolean, nullable=False, server_default='false'),
		sa.Column('link', sa.Text, nullable=True),
		sa.Column('notification_metadata', postgresql.JSONB, nullable=True),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column('read_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
	)
	op.create_index(
		'idx_user_notifications_user_created',
		'user_notifications',
		['user_id', 'created_at'],
	)
	op.create_index(
		'idx_user_notifications_user_unread',
		'user_notifications',
		['user_id', 'is_read'],
	)

	# user_favorites — pinned items per user
	op.create_table(
		'user_favorites',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column(
			'user_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('users.id', ondelete='CASCADE'),
			nullable=False, index=True,
		),
		sa.Column('tenant_id', sa.String(255), nullable=True),
		sa.Column('item_type', sa.String(32), nullable=False),
		sa.Column('item_id', sa.String(255), nullable=False),
		sa.Column('title', sa.Text, nullable=False),
		sa.Column('path', sa.Text, nullable=True),
		sa.Column('icon', sa.String(128), nullable=True),
		sa.Column('pinned_at', postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.UniqueConstraint('user_id', 'item_type', 'item_id', name='uq_user_favorite_item'),
	)

	# user_search_history — recent searches per user
	op.create_table(
		'user_search_history',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column(
			'user_id', postgresql.UUID(as_uuid=True),
			sa.ForeignKey('users.id', ondelete='CASCADE'),
			nullable=False, index=True,
		),
		sa.Column('query', sa.Text, nullable=False),
		sa.Column('filters', postgresql.JSONB, nullable=True),
		sa.Column('result_count', sa.Integer, nullable=False, server_default='0'),
		sa.Column('searched_at', postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
	)
	op.create_index(
		'idx_search_history_user_searched_at',
		'user_search_history',
		['user_id', 'searched_at'],
	)


def downgrade() -> None:
	op.drop_table('user_search_history')
	op.drop_table('user_favorites')
	op.drop_table('user_notifications')
