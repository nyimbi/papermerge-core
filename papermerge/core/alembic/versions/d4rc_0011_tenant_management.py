# (c) Copyright Datacraft, 2026
"""Add tenant storage, AI, and subscription configuration tables.

Revision ID: d4rc_0011
Revises: d4rc_0010
Create Date: 2026-01-22
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0011'
down_revision: Union[str, None] = 'd4rc_0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Create tenant_storage_config table
	op.create_table(
		'tenant_storage_config',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), unique=True, nullable=False),
		sa.Column('provider', sa.String(20), default='local', nullable=False),
		sa.Column('bucket_name', sa.String(255), nullable=True),
		sa.Column('region', sa.String(50), nullable=True),
		sa.Column('endpoint_url', sa.String(500), nullable=True),
		sa.Column('access_key_id', sa.String(255), nullable=True),
		sa.Column('secret_access_key', sa.String(500), nullable=True),
		sa.Column('base_path', sa.String(500), default='documents/', nullable=False),
		sa.Column('archive_path', sa.String(500), nullable=True),
		sa.Column('is_verified', sa.Boolean, default=False, nullable=False),
		sa.Column('last_verified_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
	)

	# Create tenant_ai_config table
	op.create_table(
		'tenant_ai_config',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), unique=True, nullable=False),
		sa.Column('provider', sa.String(20), default='openai', nullable=False),
		sa.Column('api_key', sa.String(500), nullable=True),
		sa.Column('endpoint_url', sa.String(500), nullable=True),
		sa.Column('default_model', sa.String(100), default='gpt-4o-mini', nullable=False),
		sa.Column('embedding_model', sa.String(100), default='text-embedding-3-small', nullable=False),
		sa.Column('monthly_token_limit', sa.Integer, nullable=True),
		sa.Column('tokens_used_this_month', sa.Integer, default=0, nullable=False),
		sa.Column('token_reset_day', sa.Integer, default=1, nullable=False),
		sa.Column('classification_enabled', sa.Boolean, default=True, nullable=False),
		sa.Column('extraction_enabled', sa.Boolean, default=True, nullable=False),
		sa.Column('summarization_enabled', sa.Boolean, default=True, nullable=False),
		sa.Column('chat_enabled', sa.Boolean, default=False, nullable=False),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
	)

	# Create tenant_subscriptions table
	op.create_table(
		'tenant_subscriptions',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), unique=True, nullable=False),
		sa.Column('plan', sa.String(50), default='free', nullable=False),
		sa.Column('billing_cycle', sa.String(20), default='monthly', nullable=False),
		sa.Column('stripe_subscription_id', sa.String(100), nullable=True),
		sa.Column('stripe_price_id', sa.String(100), nullable=True),
		sa.Column('current_period_start', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('current_period_end', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('cancel_at_period_end', sa.Boolean, default=False, nullable=False),
		sa.Column('canceled_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('max_users', sa.Integer, nullable=True),
		sa.Column('max_storage_gb', sa.Integer, nullable=True),
		sa.Column('max_documents', sa.Integer, nullable=True),
		sa.Column('ai_tokens_per_month', sa.Integer, nullable=True),
		sa.Column('addons', postgresql.JSONB, nullable=True),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
	)


def downgrade() -> None:
	op.drop_table('tenant_subscriptions')
	op.drop_table('tenant_ai_config')
	op.drop_table('tenant_storage_config')
