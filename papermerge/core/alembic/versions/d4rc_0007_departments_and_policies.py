# (c) Copyright Datacraft, 2026
"""Add departments and policies tables.

Revision ID: d4rc_0007
Revises: d4rc_0006
Create Date: 2026-01-20

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0007'
down_revision: Union[str, None] = 'd4rc_0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Create PolicyEffect enum
	policy_effect_enum = postgresql.ENUM('allow', 'deny', name='policyeffect', create_type=False)
	policy_effect_enum.create(op.get_bind(), checkfirst=True)

	# Create PolicyStatus enum
	policy_status_enum = postgresql.ENUM('draft', 'pending_approval', 'active', 'inactive', name='policystatus', create_type=False)
	policy_status_enum.create(op.get_bind(), checkfirst=True)

	# Departments table
	op.create_table(
		'departments',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('code', sa.String(50), nullable=True),
		sa.Column('description', sa.Text, nullable=True),
		sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True),
		sa.Column('is_active', sa.Boolean, server_default='true'),
		# Audit columns
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('deleted_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('archived_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('deleted_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('archived_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.CheckConstraint("char_length(trim(name)) > 0", name='department_name_not_empty'),
	)
	op.create_index('idx_departments_name_active_unique', 'departments', ['name'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
	op.create_index('idx_departments_code_active_unique', 'departments', ['code'], unique=True, postgresql_where=sa.text('deleted_at IS NULL AND code IS NOT NULL'))
	op.create_index('idx_departments_parent_id', 'departments', ['parent_id'])
	op.create_index('idx_departments_is_active', 'departments', ['is_active'])

	# User departments (membership) table
	op.create_table(
		'user_departments',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
		sa.Column('department_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id', ondelete='CASCADE'), nullable=False),
		sa.Column('is_head', sa.Boolean, server_default='false'),
		sa.Column('is_primary', sa.Boolean, server_default='false'),
		sa.Column('joined_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		# Audit columns
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('deleted_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('archived_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('deleted_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('archived_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
	)
	op.create_index('idx_user_departments_unique', 'user_departments', ['user_id', 'department_id'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
	op.create_index('idx_user_departments_user_id', 'user_departments', ['user_id'])
	op.create_index('idx_user_departments_department_id', 'user_departments', ['department_id'])
	op.create_index('idx_user_departments_is_head', 'user_departments', ['is_head'])

	# Department access rules table
	op.create_table(
		'department_access_rules',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('department_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id', ondelete='CASCADE'), nullable=False),
		sa.Column('document_type_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_types.id', ondelete='CASCADE'), nullable=True),
		sa.Column('permission_level', sa.String(20), server_default='view'),
		sa.Column('can_create', sa.Boolean, server_default='false'),
		sa.Column('can_share', sa.Boolean, server_default='false'),
		sa.Column('inherit_to_children', sa.Boolean, server_default='true'),
		# Audit columns
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('deleted_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('archived_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('deleted_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('archived_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.CheckConstraint("permission_level IN ('none', 'view', 'edit', 'delete', 'admin')", name='valid_permission_level'),
	)
	op.create_index('idx_department_access_rules_unique', 'department_access_rules', ['department_id', 'document_type_id'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
	op.create_index('idx_department_access_rules_department_id', 'department_access_rules', ['department_id'])
	op.create_index('idx_department_access_rules_document_type_id', 'department_access_rules', ['document_type_id'])

	# Policies table
	op.create_table(
		'policies',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.Text, server_default=''),
		sa.Column('effect', postgresql.ENUM('allow', 'deny', name='policyeffect', create_type=False), nullable=False),
		sa.Column('priority', sa.Integer, server_default='100'),
		sa.Column('rules_json', postgresql.JSON, server_default='[]'),
		sa.Column('actions', postgresql.JSON, server_default='[]'),
		sa.Column('resource_types', postgresql.JSON, server_default='[]'),
		sa.Column('status', postgresql.ENUM('draft', 'pending_approval', 'active', 'inactive', name='policystatus', create_type=False), server_default='draft'),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=True),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('valid_from', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('valid_until', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('dsl_text', sa.Text, nullable=True),
		sa.Column('metadata_json', postgresql.JSON, server_default='{}'),
	)
	op.create_index('ix_policies_tenant_status', 'policies', ['tenant_id', 'status'])
	op.create_index('ix_policies_effect_priority', 'policies', ['effect', 'priority'])

	# Policy approvals table
	op.create_table(
		'policy_approvals',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('policy_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('policies.id', ondelete='CASCADE'), nullable=False),
		sa.Column('requested_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('requested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('status', sa.String(20), server_default='pending'),
		sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('reviewed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('comments', sa.Text, nullable=True),
		sa.Column('policy_snapshot', postgresql.JSON, server_default='{}'),
		sa.Column('changes_summary', sa.Text, nullable=True),
	)
	op.create_index('ix_policy_approvals_status', 'policy_approvals', ['status'])
	op.create_index('ix_policy_approvals_policy_id', 'policy_approvals', ['policy_id'])

	# Policy evaluation logs table
	op.create_table(
		'policy_evaluation_logs',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('policy_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('policies.id', ondelete='SET NULL'), nullable=True),
		sa.Column('timestamp', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), index=True),
		sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
		sa.Column('subject_username', sa.String(255), nullable=True),
		sa.Column('resource_id', postgresql.UUID(as_uuid=True), nullable=False),
		sa.Column('resource_type', sa.String(50), nullable=False),
		sa.Column('action', sa.String(50), nullable=False),
		sa.Column('allowed', sa.Boolean, nullable=False),
		sa.Column('effect', postgresql.ENUM('allow', 'deny', name='policyeffect', create_type=False), nullable=False),
		sa.Column('reason', sa.Text, nullable=True),
		sa.Column('evaluation_time_ms', sa.Integer, server_default='0'),
		sa.Column('context_snapshot', postgresql.JSON, server_default='{}'),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=True),
	)
	op.create_index('ix_policy_eval_logs_subject_action', 'policy_evaluation_logs', ['subject_id', 'action'])
	op.create_index('ix_policy_eval_logs_resource', 'policy_evaluation_logs', ['resource_id', 'resource_type'])
	op.create_index('ix_policy_eval_logs_tenant_time', 'policy_evaluation_logs', ['tenant_id', 'timestamp'])

	# Department access grants table
	op.create_table(
		'department_access_grants',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
		sa.Column('department_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id', ondelete='CASCADE'), nullable=False),
		sa.Column('granted_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('granted_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('reason', sa.Text, nullable=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=True),
	)
	op.create_index('ix_dept_access_user_dept', 'department_access_grants', ['user_id', 'department_id'])
	op.create_index('ix_dept_access_expires', 'department_access_grants', ['expires_at'])


def downgrade() -> None:
	op.drop_table('department_access_grants')
	op.drop_table('policy_evaluation_logs')
	op.drop_table('policy_approvals')
	op.drop_table('policies')
	op.drop_table('department_access_rules')
	op.drop_table('user_departments')
	op.drop_table('departments')

	# Drop enums
	op.execute("DROP TYPE IF EXISTS policyeffect")
	op.execute("DROP TYPE IF EXISTS policystatus")
