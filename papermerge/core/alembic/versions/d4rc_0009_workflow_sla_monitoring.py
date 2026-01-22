# (c) Copyright Datacraft, 2026
"""Add workflow SLA monitoring tables and columns.

Revision ID: d4rc_0009
Revises: d4rc_0008
Create Date: 2026-01-22

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0009'
down_revision: Union[str, None] = 'd4rc_0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Create workflow_escalation_chains table
	op.create_table(
		'workflow_escalation_chains',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('name', sa.String(100), nullable=False),
		sa.Column('description', sa.Text, nullable=True),
		sa.Column('is_active', sa.Boolean, default=True, nullable=False),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
	)

	# Create workflow_escalation_levels table
	op.create_table(
		'workflow_escalation_levels',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('chain_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_escalation_chains.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('level_order', sa.Integer, nullable=False),
		sa.Column('target_type', sa.String(20), nullable=False),
		sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=True),
		sa.Column('wait_hours', sa.Integer, default=24, nullable=False),
		sa.Column('notify_on_escalation', sa.Boolean, default=True, nullable=False),
	)

	# Create workflow_task_sla_configs table
	op.create_table(
		'workflow_task_sla_configs',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=True),
		sa.Column('step_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_steps.id', ondelete='CASCADE'), nullable=True),
		sa.Column('name', sa.String(100), nullable=False),
		sa.Column('target_hours', sa.Integer, nullable=False),
		sa.Column('warning_threshold_percent', sa.Integer, default=75, nullable=False),
		sa.Column('critical_threshold_percent', sa.Integer, default=90, nullable=False),
		sa.Column('reminder_enabled', sa.Boolean, default=True, nullable=False),
		sa.Column('reminder_thresholds', postgresql.JSONB, nullable=True),
		sa.Column('escalation_chain_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_escalation_chains.id', ondelete='SET NULL'), nullable=True),
		sa.Column('is_active', sa.Boolean, default=True, nullable=False),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
	)
	op.create_index('idx_sla_config_workflow', 'workflow_task_sla_configs', ['workflow_id'])
	op.create_index('idx_sla_config_step', 'workflow_task_sla_configs', ['step_id'])

	# Create workflow_task_metrics table
	op.create_table(
		'workflow_task_metrics',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
		sa.Column('instance_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_instances.id', ondelete='CASCADE'), nullable=False),
		sa.Column('step_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_steps.id', ondelete='SET NULL'), nullable=True),
		sa.Column('execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_step_executions.id', ondelete='SET NULL'), nullable=True),
		sa.Column('step_type', sa.String(50), nullable=True),
		sa.Column('sla_config_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_task_sla_configs.id', ondelete='SET NULL'), nullable=True),
		sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), nullable=False),
		sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('target_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('duration_seconds', sa.Integer, nullable=True),
		sa.Column('target_seconds', sa.Integer, nullable=True),
		sa.Column('sla_status', sa.String(20), default='on_track', nullable=False),
		sa.Column('breached_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
	)
	op.create_index('idx_task_metrics_sla_status', 'workflow_task_metrics', ['sla_status', 'tenant_id'])
	op.create_index('idx_task_metrics_workflow', 'workflow_task_metrics', ['workflow_id', 'created_at'])

	# Create workflow_sla_alerts table
	op.create_table(
		'workflow_sla_alerts',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('metric_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_task_metrics.id', ondelete='SET NULL'), nullable=True),
		sa.Column('approval_request_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_approval_requests.id', ondelete='SET NULL'), nullable=True),
		sa.Column('alert_type', sa.String(30), nullable=False),
		sa.Column('severity', sa.String(20), default='medium', nullable=False),
		sa.Column('title', sa.String(255), nullable=False),
		sa.Column('message', sa.Text, nullable=True),
		sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='SET NULL'), nullable=True),
		sa.Column('instance_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_instances.id', ondelete='SET NULL'), nullable=True),
		sa.Column('step_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_steps.id', ondelete='SET NULL'), nullable=True),
		sa.Column('assignee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('acknowledged', sa.Boolean, default=False, nullable=False),
		sa.Column('acknowledged_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
		sa.Column('acknowledged_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
	)
	op.create_index('idx_sla_alerts_unack', 'workflow_sla_alerts', ['tenant_id', 'acknowledged'])
	op.create_index('idx_sla_alerts_assignee', 'workflow_sla_alerts', ['assignee_id', 'acknowledged'])

	# Create workflow_approval_reminders table
	op.create_table(
		'workflow_approval_reminders',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('approval_request_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_approval_requests.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('threshold_percent', sa.Integer, nullable=False),
		sa.Column('sent_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
		sa.Column('channel', sa.String(20), nullable=False),
	)

	# Add columns to workflow_steps
	op.add_column('workflow_steps', sa.Column('sla_config_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_task_sla_configs.id', ondelete='SET NULL'), nullable=True))
	op.add_column('workflow_steps', sa.Column('reminder_enabled', sa.Boolean, default=True, server_default='true', nullable=False))

	# Add columns to workflow_approval_requests
	op.add_column('workflow_approval_requests', sa.Column('escalation_chain_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_escalation_chains.id', ondelete='SET NULL'), nullable=True))
	op.add_column('workflow_approval_requests', sa.Column('current_escalation_level', sa.Integer, default=0, server_default='0', nullable=False))
	op.add_column('workflow_approval_requests', sa.Column('last_reminder_threshold', sa.Integer, nullable=True))
	op.add_column('workflow_approval_requests', sa.Column('delegated_from_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
	op.add_column('workflow_approval_requests', sa.Column('delegated_at', postgresql.TIMESTAMP(timezone=True), nullable=True))
	op.add_column('workflow_approval_requests', sa.Column('delegation_reason', sa.Text, nullable=True))


def downgrade() -> None:
	# Remove columns from workflow_approval_requests
	op.drop_column('workflow_approval_requests', 'delegation_reason')
	op.drop_column('workflow_approval_requests', 'delegated_at')
	op.drop_column('workflow_approval_requests', 'delegated_from_id')
	op.drop_column('workflow_approval_requests', 'last_reminder_threshold')
	op.drop_column('workflow_approval_requests', 'current_escalation_level')
	op.drop_column('workflow_approval_requests', 'escalation_chain_id')

	# Remove columns from workflow_steps
	op.drop_column('workflow_steps', 'reminder_enabled')
	op.drop_column('workflow_steps', 'sla_config_id')

	# Drop tables in reverse order
	op.drop_table('workflow_approval_reminders')
	op.drop_index('idx_sla_alerts_assignee', 'workflow_sla_alerts')
	op.drop_index('idx_sla_alerts_unack', 'workflow_sla_alerts')
	op.drop_table('workflow_sla_alerts')
	op.drop_index('idx_task_metrics_workflow', 'workflow_task_metrics')
	op.drop_index('idx_task_metrics_sla_status', 'workflow_task_metrics')
	op.drop_table('workflow_task_metrics')
	op.drop_index('idx_sla_config_step', 'workflow_task_sla_configs')
	op.drop_index('idx_sla_config_workflow', 'workflow_task_sla_configs')
	op.drop_table('workflow_task_sla_configs')
	op.drop_table('workflow_escalation_levels')
	op.drop_table('workflow_escalation_chains')
