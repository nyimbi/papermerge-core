# (c) Copyright Datacraft, 2026
"""Add tenant_id to users table for multi-tenancy.

Revision ID: d4rc_0006
Revises: d4rc_0005
Create Date: 2026-01-19

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0006'
down_revision: Union[str, None] = 'd4rc_0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default tenant UUID for existing users
DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000001'


def upgrade() -> None:
	# Add missing columns to tenants table if they don't exist
	op.add_column('tenants', sa.Column('custom_domain', sa.String(255), unique=True, nullable=True))
	op.add_column('tenants', sa.Column('subdomain', sa.String(100), nullable=True))
	op.add_column('tenants', sa.Column('plan', sa.String(50), server_default='free', nullable=True))
	op.add_column('tenants', sa.Column('features', postgresql.JSONB, nullable=True))

	# First, ensure default tenant exists
	op.execute(f"""
		INSERT INTO tenants (id, name, slug, status, plan, created_at, updated_at)
		VALUES (
			'{DEFAULT_TENANT_ID}'::uuid,
			'Default Tenant',
			'default',
			'active',
			'enterprise',
			NOW(),
			NOW()
		)
		ON CONFLICT (id) DO NOTHING
	""")

	# Add tenant_id column with default value
	op.add_column(
		'users',
		sa.Column(
			'tenant_id',
			postgresql.UUID(as_uuid=True),
			nullable=False,
			server_default=DEFAULT_TENANT_ID,
			comment='Tenant this user belongs to',
		),
	)

	# Create index for tenant queries
	op.create_index(
		'idx_users_tenant_id',
		'users',
		['tenant_id'],
	)

	# Add foreign key constraint
	op.create_foreign_key(
		'fk_users_tenant_id',
		'users',
		'tenants',
		['tenant_id'],
		['id'],
		ondelete='CASCADE',
	)

	# Remove server default after data migration (keep model default)
	op.alter_column('users', 'tenant_id', server_default=None)


def downgrade() -> None:
	op.drop_constraint('fk_users_tenant_id', 'users', type_='foreignkey')
	op.drop_index('idx_users_tenant_id', table_name='users')
	op.drop_column('users', 'tenant_id')
	# Remove columns added to tenants table
	op.drop_column('tenants', 'features')
	op.drop_column('tenants', 'plan')
	op.drop_column('tenants', 'subdomain')
	op.drop_column('tenants', 'custom_domain')
