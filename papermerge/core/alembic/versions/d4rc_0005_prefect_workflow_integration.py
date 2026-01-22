# (c) Copyright Datacraft, 2026
"""Add Prefect workflow engine integration columns.

Revision ID: d4rc_0005
Revises: d4rc_0004
Create Date: 2026-01-18

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4rc_0005'
down_revision: Union[str, None] = 'd4rc_0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Add Prefect flow run ID to workflow instances
	op.add_column(
		'workflow_instances',
		sa.Column(
			'prefect_flow_run_id',
			postgresql.UUID(as_uuid=True),
			nullable=True,
			comment='Prefect flow run ID for execution tracking',
		),
	)
	op.create_index(
		'idx_workflow_instances_prefect_run',
		'workflow_instances',
		['prefect_flow_run_id'],
		unique=True,
		postgresql_where=sa.text('prefect_flow_run_id IS NOT NULL'),
	)

	# Add Prefect task run ID to step executions
	op.add_column(
		'workflow_step_executions',
		sa.Column(
			'prefect_task_run_id',
			postgresql.UUID(as_uuid=True),
			nullable=True,
			comment='Prefect task run ID for step tracking',
		),
	)
	op.create_index(
		'idx_step_executions_prefect_task',
		'workflow_step_executions',
		['prefect_task_run_id'],
	)

	# Add result storage for task outputs
	op.add_column(
		'workflow_step_executions',
		sa.Column(
			'result_data',
			postgresql.JSONB,
			nullable=True,
			comment='Task execution result data',
		),
	)

	# Add error tracking
	op.add_column(
		'workflow_step_executions',
		sa.Column(
			'error_message',
			sa.Text,
			nullable=True,
			comment='Error message if task failed',
		),
	)
	op.add_column(
		'workflow_step_executions',
		sa.Column(
			'retry_count',
			sa.Integer,
			nullable=False,
			server_default='0',
			comment='Number of retry attempts',
		),
	)

	# Add Prefect deployment ID to workflows
	op.add_column(
		'workflows',
		sa.Column(
			'prefect_deployment_id',
			postgresql.UUID(as_uuid=True),
			nullable=True,
			comment='Prefect deployment ID for this workflow',
		),
	)

	# Add React Flow graph storage for visual designer
	op.add_column(
		'workflows',
		sa.Column(
			'nodes',
			postgresql.JSONB,
			nullable=True,
			comment='React Flow nodes JSON',
		),
	)
	op.add_column(
		'workflows',
		sa.Column(
			'edges',
			postgresql.JSONB,
			nullable=True,
			comment='React Flow edges JSON',
		),
	)
	op.add_column(
		'workflows',
		sa.Column(
			'viewport',
			postgresql.JSONB,
			nullable=True,
			comment='React Flow viewport state',
		),
	)

	# Add step_type to workflow steps (for Prefect task mapping)
	# First check if column exists (may exist from original schema)
	# Add node_id for linking steps to React Flow nodes
	op.add_column(
		'workflow_steps',
		sa.Column(
			'node_id',
			sa.String(100),
			nullable=True,
			comment='React Flow node ID',
		),
	)
	op.add_column(
		'workflow_steps',
		sa.Column(
			'config',
			postgresql.JSONB,
			nullable=True,
			comment='Task configuration parameters',
		),
	)

	# Create workflow approval requests table (for human-in-the-loop)
	op.create_table(
		'workflow_approval_requests',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column(
			'instance_id',
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey('workflow_instances.id', ondelete='CASCADE'),
			nullable=False,
		),
		sa.Column(
			'step_id',
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey('workflow_steps.id', ondelete='CASCADE'),
			nullable=False,
		),
		sa.Column(
			'execution_id',
			postgresql.UUID(as_uuid=True),
			sa.ForeignKey('workflow_step_executions.id', ondelete='CASCADE'),
			nullable=False,
		),
		sa.Column(
			'prefect_flow_run_id',
			postgresql.UUID(as_uuid=True),
			nullable=True,
		),
		sa.Column('approval_type', sa.String(50), nullable=False),  # approval, review, signature
		sa.Column('title', sa.String(255), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='SET NULL')),
		sa.Column('requester_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('assignee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('assignee_role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('roles.id', ondelete='SET NULL')),
		sa.Column('assignee_group_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('groups.id', ondelete='SET NULL')),
		sa.Column('status', sa.String(30), server_default='pending'),  # pending, approved, rejected, expired
		sa.Column('priority', sa.String(20), server_default='normal'),  # low, normal, high, urgent
		sa.Column('decision', sa.String(50)),  # approved, rejected, returned
		sa.Column('decision_notes', sa.Text),
		sa.Column('decided_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('decided_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('deadline_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('escalated_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('escalated_to', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('reminder_sent_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('context_data', postgresql.JSONB),  # Additional context for approver
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_approval_requests_instance', 'workflow_approval_requests', ['instance_id'])
	op.create_index('idx_approval_requests_assignee', 'workflow_approval_requests', ['assignee_id', 'status'])
	op.create_index('idx_approval_requests_deadline', 'workflow_approval_requests', ['deadline_at', 'status'])
	op.create_index('idx_approval_requests_prefect', 'workflow_approval_requests', ['prefect_flow_run_id'])


def downgrade() -> None:
	op.drop_table('workflow_approval_requests')

	op.drop_column('workflow_steps', 'config')
	op.drop_column('workflow_steps', 'node_id')

	op.drop_column('workflows', 'viewport')
	op.drop_column('workflows', 'edges')
	op.drop_column('workflows', 'nodes')
	op.drop_column('workflows', 'prefect_deployment_id')

	op.drop_column('workflow_step_executions', 'retry_count')
	op.drop_column('workflow_step_executions', 'error_message')
	op.drop_column('workflow_step_executions', 'result_data')
	op.drop_index('idx_step_executions_prefect_task', 'workflow_step_executions')
	op.drop_column('workflow_step_executions', 'prefect_task_run_id')

	op.drop_index('idx_workflow_instances_prefect_run', 'workflow_instances')
	op.drop_column('workflow_instances', 'prefect_flow_run_id')
