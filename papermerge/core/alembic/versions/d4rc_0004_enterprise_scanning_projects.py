# (c) Copyright Datacraft, 2026
"""Enterprise-scale scanning project management extensions.

Adds support for million-document digitization projects with:
- Hierarchical sub-projects
- Multi-site locations
- Shift management
- Cost tracking and budgets
- SLA management
- Equipment maintenance
- Operator certifications
- Capacity planning
- Priority queues
- Contracts
- Workload forecasting
- Project checkpoints

Revision ID: d4rc_0004
Revises: d4rc_0003
Create Date: 2026-01-18

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd4rc_0004'
down_revision: Union[str, None] = 'd4rc_0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# =====================================================
	# Sub-Projects for Hierarchical Organization
	# =====================================================
	op.create_table(
		'sub_projects',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('parent_project_id', sa.String(36), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('code', sa.String(50), nullable=False, index=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.String(2000)),
		sa.Column('category', sa.String(100)),
		sa.Column('status', sa.String(50), nullable=False, server_default='planning'),
		sa.Column('priority', sa.Integer, server_default='5'),
		sa.Column('total_estimated_pages', sa.Integer, server_default='0'),
		sa.Column('scanned_pages', sa.Integer, server_default='0'),
		sa.Column('verified_pages', sa.Integer, server_default='0'),
		sa.Column('rejected_pages', sa.Integer, server_default='0'),
		sa.Column('assigned_location_id', sa.String(36)),
		sa.Column('start_date', sa.DateTime),
		sa.Column('target_end_date', sa.DateTime),
		sa.Column('actual_end_date', sa.DateTime),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
		sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
	)
	op.create_index('idx_sub_projects_category', 'sub_projects', ['category'])
	op.create_index('idx_sub_projects_status', 'sub_projects', ['status'])

	# =====================================================
	# Scanning Locations (Multi-Site Operations)
	# =====================================================
	op.create_table(
		'scanning_locations',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
		sa.Column('code', sa.String(50), nullable=False, unique=True, index=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('address', sa.String(500)),
		sa.Column('city', sa.String(100)),
		sa.Column('country', sa.String(100)),
		sa.Column('timezone', sa.String(50), server_default='UTC'),
		sa.Column('is_active', sa.Boolean, server_default='true'),
		sa.Column('scanner_capacity', sa.Integer, server_default='1'),
		sa.Column('operator_capacity', sa.Integer, server_default='2'),
		sa.Column('daily_page_capacity', sa.Integer, server_default='5000'),
		sa.Column('contact_name', sa.String(255)),
		sa.Column('contact_email', sa.String(255)),
		sa.Column('contact_phone', sa.String(50)),
		sa.Column('notes', sa.String(2000)),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
		sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
	)

	# =====================================================
	# Shift Management
	# =====================================================
	op.create_table(
		'scanning_shifts',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
		sa.Column('location_id', sa.String(36)),
		sa.Column('name', sa.String(100), nullable=False),
		sa.Column('start_time', sa.String(10), nullable=False),
		sa.Column('end_time', sa.String(10), nullable=False),
		sa.Column('days_of_week', sa.String(20), server_default='1,2,3,4,5'),
		sa.Column('target_pages_per_operator', sa.Integer, server_default='500'),
		sa.Column('break_minutes', sa.Integer, server_default='60'),
		sa.Column('is_active', sa.Boolean, server_default='true'),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
	)

	op.create_table(
		'shift_assignments',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('shift_id', sa.String(36), sa.ForeignKey('scanning_shifts.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('operator_id', sa.String(36), nullable=False, index=True),
		sa.Column('operator_name', sa.String(255)),
		sa.Column('project_id', sa.String(36)),
		sa.Column('assignment_date', sa.DateTime, nullable=False, index=True),
		sa.Column('status', sa.String(50), server_default='scheduled'),
		sa.Column('actual_start', sa.DateTime),
		sa.Column('actual_end', sa.DateTime),
		sa.Column('pages_scanned', sa.Integer, server_default='0'),
		sa.Column('notes', sa.String(1000)),
	)

	# =====================================================
	# Cost Tracking
	# =====================================================
	op.create_table(
		'project_costs',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('project_id', sa.String(36), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('cost_date', sa.DateTime, nullable=False, index=True),
		sa.Column('cost_type', sa.String(50), nullable=False),
		sa.Column('category', sa.String(100)),
		sa.Column('description', sa.String(500)),
		sa.Column('quantity', sa.Float, server_default='1.0'),
		sa.Column('unit_cost', sa.Float, server_default='0.0'),
		sa.Column('total_cost', sa.Float, server_default='0.0'),
		sa.Column('currency', sa.String(3), server_default='USD'),
		sa.Column('operator_id', sa.String(36)),
		sa.Column('location_id', sa.String(36)),
		sa.Column('batch_id', sa.String(36)),
		sa.Column('notes', sa.String(1000)),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
	)
	op.create_index('idx_project_costs_type', 'project_costs', ['cost_type'])

	op.create_table(
		'project_budgets',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('project_id', sa.String(36), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('budget_name', sa.String(255), nullable=False),
		sa.Column('total_budget', sa.Float, server_default='0.0'),
		sa.Column('labor_budget', sa.Float, server_default='0.0'),
		sa.Column('equipment_budget', sa.Float, server_default='0.0'),
		sa.Column('materials_budget', sa.Float, server_default='0.0'),
		sa.Column('storage_budget', sa.Float, server_default='0.0'),
		sa.Column('other_budget', sa.Float, server_default='0.0'),
		sa.Column('contingency_budget', sa.Float, server_default='0.0'),
		sa.Column('currency', sa.String(3), server_default='USD'),
		sa.Column('spent_to_date', sa.Float, server_default='0.0'),
		sa.Column('cost_per_page', sa.Float),
		sa.Column('target_cost_per_page', sa.Float),
		sa.Column('is_approved', sa.Boolean, server_default='false'),
		sa.Column('approved_by_id', sa.String(36)),
		sa.Column('approved_at', sa.DateTime),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
		sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
	)

	# =====================================================
	# SLA Management
	# =====================================================
	op.create_table(
		'project_slas',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('project_id', sa.String(36), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.String(1000)),
		sa.Column('sla_type', sa.String(50), nullable=False),
		sa.Column('target_value', sa.Float, nullable=False),
		sa.Column('target_unit', sa.String(50), nullable=False),
		sa.Column('current_value', sa.Float, server_default='0.0'),
		sa.Column('threshold_warning', sa.Float),
		sa.Column('threshold_critical', sa.Float),
		sa.Column('status', sa.String(50), server_default='on_track'),
		sa.Column('penalty_amount', sa.Float),
		sa.Column('penalty_currency', sa.String(3), server_default='USD'),
		sa.Column('start_date', sa.DateTime, nullable=False),
		sa.Column('end_date', sa.DateTime, nullable=False),
		sa.Column('last_checked_at', sa.DateTime),
		sa.Column('breached_at', sa.DateTime),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
	)
	op.create_index('idx_project_slas_status', 'project_slas', ['status'])

	op.create_table(
		'sla_alerts',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('sla_id', sa.String(36), sa.ForeignKey('project_slas.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('alert_type', sa.String(50), nullable=False),
		sa.Column('alert_time', sa.DateTime, server_default=sa.func.now()),
		sa.Column('message', sa.String(1000), nullable=False),
		sa.Column('current_value', sa.Float, nullable=False),
		sa.Column('target_value', sa.Float, nullable=False),
		sa.Column('acknowledged_by_id', sa.String(36)),
		sa.Column('acknowledged_at', sa.DateTime),
		sa.Column('resolution_notes', sa.String(2000)),
	)
	op.create_index('idx_sla_alerts_type', 'sla_alerts', ['alert_type'])

	# =====================================================
	# Equipment Maintenance
	# =====================================================
	op.create_table(
		'equipment_maintenance',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('resource_id', sa.String(36), sa.ForeignKey('scanning_resources.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('maintenance_type', sa.String(50), nullable=False),
		sa.Column('title', sa.String(255), nullable=False),
		sa.Column('description', sa.String(2000)),
		sa.Column('scheduled_date', sa.DateTime, nullable=False, index=True),
		sa.Column('completed_date', sa.DateTime),
		sa.Column('status', sa.String(50), server_default='scheduled'),
		sa.Column('priority', sa.Integer, server_default='5'),
		sa.Column('estimated_downtime_hours', sa.Float, server_default='1.0'),
		sa.Column('actual_downtime_hours', sa.Float),
		sa.Column('technician_name', sa.String(255)),
		sa.Column('cost', sa.Float, server_default='0.0'),
		sa.Column('parts_replaced', sa.String(1000)),
		sa.Column('notes', sa.String(2000)),
		sa.Column('next_maintenance_date', sa.DateTime),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
	)
	op.create_index('idx_equipment_maintenance_status', 'equipment_maintenance', ['status'])

	# =====================================================
	# Operator Certifications
	# =====================================================
	op.create_table(
		'operator_certifications',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('operator_id', sa.String(36), nullable=False, index=True),
		sa.Column('operator_name', sa.String(255)),
		sa.Column('certification_type', sa.String(100), nullable=False),
		sa.Column('certification_name', sa.String(255), nullable=False),
		sa.Column('level', sa.String(50), server_default='basic'),
		sa.Column('issued_date', sa.DateTime, nullable=False),
		sa.Column('expiry_date', sa.DateTime),
		sa.Column('issued_by', sa.String(255)),
		sa.Column('is_active', sa.Boolean, server_default='true'),
		sa.Column('score', sa.Float),
		sa.Column('notes', sa.String(1000)),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
	)
	op.create_index('idx_operator_certifications_type', 'operator_certifications', ['certification_type'])
	op.create_index('idx_operator_certifications_active', 'operator_certifications', ['is_active', 'expiry_date'])

	# =====================================================
	# Capacity Planning
	# =====================================================
	op.create_table(
		'capacity_plans',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('project_id', sa.String(36), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('plan_name', sa.String(255), nullable=False),
		sa.Column('plan_date', sa.DateTime, server_default=sa.func.now()),
		sa.Column('target_completion_date', sa.DateTime, nullable=False),
		sa.Column('total_pages_remaining', sa.Integer, server_default='0'),
		sa.Column('working_days_remaining', sa.Integer, server_default='0'),
		sa.Column('required_pages_per_day', sa.Integer, server_default='0'),
		sa.Column('current_daily_capacity', sa.Integer, server_default='0'),
		sa.Column('capacity_gap', sa.Integer, server_default='0'),
		sa.Column('recommended_operators', sa.Integer, server_default='0'),
		sa.Column('recommended_scanners', sa.Integer, server_default='0'),
		sa.Column('recommended_shifts_per_day', sa.Integer, server_default='1'),
		sa.Column('confidence_score', sa.Float, server_default='0.7'),
		sa.Column('assumptions', sa.String(2000)),
		sa.Column('recommendations', sa.String(2000)),
		sa.Column('created_by_id', sa.String(36)),
		sa.Column('is_approved', sa.Boolean, server_default='false'),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
	)

	# =====================================================
	# Document Type Distribution
	# =====================================================
	op.create_table(
		'document_type_distributions',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('project_id', sa.String(36), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('document_type', sa.String(100), nullable=False, index=True),
		sa.Column('document_type_name', sa.String(255), nullable=False),
		sa.Column('estimated_count', sa.Integer, server_default='0'),
		sa.Column('actual_count', sa.Integer, server_default='0'),
		sa.Column('estimated_pages', sa.Integer, server_default='0'),
		sa.Column('actual_pages', sa.Integer, server_default='0'),
		sa.Column('avg_pages_per_document', sa.Float, server_default='1.0'),
		sa.Column('requires_special_handling', sa.Boolean, server_default='false'),
		sa.Column('special_handling_notes', sa.String(1000)),
		sa.Column('priority', sa.Integer, server_default='5'),
		sa.Column('assigned_operator_ids', sa.String(1000)),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
		sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
	)

	# =====================================================
	# Priority Queue
	# =====================================================
	op.create_table(
		'batch_priority_queue',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('batch_id', sa.String(36), sa.ForeignKey('scanning_batches.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('priority', sa.Integer, server_default='5', index=True),
		sa.Column('priority_reason', sa.String(500)),
		sa.Column('due_date', sa.DateTime, index=True),
		sa.Column('is_rush', sa.Boolean, server_default='false'),
		sa.Column('rush_approved_by_id', sa.String(36)),
		sa.Column('rush_approved_at', sa.DateTime),
		sa.Column('estimated_completion', sa.DateTime),
		sa.Column('actual_completion', sa.DateTime),
		sa.Column('queue_position', sa.Integer),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
		sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
	)
	op.create_index('idx_batch_priority_queue_rush', 'batch_priority_queue', ['is_rush', 'priority'])

	# =====================================================
	# Project Contracts
	# =====================================================
	op.create_table(
		'project_contracts',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('project_id', sa.String(36), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('contract_number', sa.String(100), nullable=False, index=True),
		sa.Column('client_name', sa.String(255), nullable=False),
		sa.Column('client_contact_name', sa.String(255)),
		sa.Column('client_contact_email', sa.String(255)),
		sa.Column('contract_type', sa.String(50), nullable=False),
		sa.Column('contract_value', sa.Float, server_default='0.0'),
		sa.Column('currency', sa.String(3), server_default='USD'),
		sa.Column('price_per_page', sa.Float),
		sa.Column('minimum_pages', sa.Integer),
		sa.Column('maximum_pages', sa.Integer),
		sa.Column('payment_terms', sa.String(500)),
		sa.Column('start_date', sa.DateTime, nullable=False),
		sa.Column('end_date', sa.DateTime, nullable=False),
		sa.Column('deliverables', sa.String(2000)),
		sa.Column('special_requirements', sa.String(2000)),
		sa.Column('status', sa.String(50), server_default='active'),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
		sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
	)

	# =====================================================
	# Workload Forecasting
	# =====================================================
	op.create_table(
		'workload_forecasts',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('project_id', sa.String(36), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('forecast_date', sa.DateTime, nullable=False, index=True),
		sa.Column('forecast_period_start', sa.DateTime, nullable=False),
		sa.Column('forecast_period_end', sa.DateTime, nullable=False),
		sa.Column('predicted_pages', sa.Integer, server_default='0'),
		sa.Column('predicted_operators_needed', sa.Integer, server_default='0'),
		sa.Column('predicted_scanners_needed', sa.Integer, server_default='0'),
		sa.Column('confidence_score', sa.Float, server_default='0.7'),
		sa.Column('model_used', sa.String(100)),
		sa.Column('actual_pages', sa.Integer),
		sa.Column('accuracy', sa.Float),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
	)

	# =====================================================
	# Project Checkpoints
	# =====================================================
	op.create_table(
		'project_checkpoints',
		sa.Column('id', sa.String(36), primary_key=True),
		sa.Column('project_id', sa.String(36), sa.ForeignKey('scanning_projects.id', ondelete='CASCADE'), nullable=False, index=True),
		sa.Column('checkpoint_number', sa.Integer, nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.String(1000)),
		sa.Column('checkpoint_type', sa.String(50), nullable=False),
		sa.Column('target_date', sa.DateTime, nullable=False),
		sa.Column('actual_date', sa.DateTime),
		sa.Column('target_percentage', sa.Float, nullable=False),
		sa.Column('actual_percentage', sa.Float),
		sa.Column('status', sa.String(50), server_default='pending'),
		sa.Column('pass_criteria', sa.String(2000)),
		sa.Column('review_notes', sa.String(2000)),
		sa.Column('reviewed_by_id', sa.String(36)),
		sa.Column('reviewed_by_name', sa.String(255)),
		sa.Column('reviewed_at', sa.DateTime),
		sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
	)
	op.create_index('idx_project_checkpoints_status', 'project_checkpoints', ['status'])
	op.create_index('idx_project_checkpoints_date', 'project_checkpoints', ['target_date'])


def downgrade() -> None:
	op.drop_table('project_checkpoints')
	op.drop_table('workload_forecasts')
	op.drop_table('project_contracts')
	op.drop_table('batch_priority_queue')
	op.drop_table('document_type_distributions')
	op.drop_table('capacity_plans')
	op.drop_table('operator_certifications')
	op.drop_table('equipment_maintenance')
	op.drop_table('sla_alerts')
	op.drop_table('project_slas')
	op.drop_table('project_budgets')
	op.drop_table('project_costs')
	op.drop_table('shift_assignments')
	op.drop_table('scanning_shifts')
	op.drop_table('scanning_locations')
	op.drop_table('sub_projects')
