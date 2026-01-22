# (c) Copyright Datacraft, 2026
"""dArchiva foundation tables - tenants, workflows, routing, bundles, cases, portfolios, forms, encryption, ingestion.

Revision ID: d4rc_0001
Revises:
Create Date: 2026-01-18

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4rc_0001'
down_revision: Union[str, None] = 'bb19aac50bca'  # Extends core papermerge migrations
branch_labels: Union[str, Sequence[str], None] = ('darchiva',)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Tenants
	op.create_table(
		'tenants',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('slug', sa.String(100), unique=True, nullable=False),
		sa.Column('status', sa.String(20), server_default='active'),
		sa.Column('contact_email', sa.String(255)),
		sa.Column('contact_phone', sa.String(50)),
		sa.Column('billing_email', sa.String(255)),
		sa.Column('stripe_customer_id', sa.String(100)),
		sa.Column('max_users', sa.Integer),
		sa.Column('max_storage_gb', sa.Integer),
		sa.Column('trial_ends_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)

	op.create_table(
		'tenant_branding',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), unique=True, nullable=False),
		sa.Column('logo_url', sa.String(500)),
		sa.Column('logo_dark_url', sa.String(500)),
		sa.Column('favicon_url', sa.String(500)),
		sa.Column('primary_color', sa.String(20), server_default='#228be6'),
		sa.Column('secondary_color', sa.String(20), server_default='#868e96'),
		sa.Column('login_background_url', sa.String(500)),
		sa.Column('login_message', sa.Text),
		sa.Column('email_header_html', sa.Text),
		sa.Column('email_footer_html', sa.Text),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)

	op.create_table(
		'tenant_settings',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), unique=True, nullable=False),
		sa.Column('document_numbering_scheme', sa.String(100), server_default='{YEAR}-{SEQ:6}'),
		sa.Column('default_language', sa.String(10), server_default='en'),
		sa.Column('storage_quota_gb', sa.Integer),
		sa.Column('warn_at_percentage', sa.Integer, server_default='80'),
		sa.Column('default_retention_days', sa.Integer),
		sa.Column('auto_archive_days', sa.Integer),
		sa.Column('ocr_enabled', sa.Boolean, server_default='true'),
		sa.Column('ai_features_enabled', sa.Boolean, server_default='true'),
		sa.Column('workflow_enabled', sa.Boolean, server_default='true'),
		sa.Column('encryption_enabled', sa.Boolean, server_default='false'),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)

	# Portfolios (before cases due to FK)
	op.create_table(
		'portfolios',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('code', sa.String(50)),
		sa.Column('description', sa.Text),
		sa.Column('status', sa.String(20), server_default='active'),
		sa.Column('client_name', sa.String(255)),
		sa.Column('client_id', sa.String(100)),
		sa.Column('metadata', postgresql.JSONB),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('deleted_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('archived_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT', deferrable=True, initially='DEFERRED'), nullable=False),
		sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT', deferrable=True, initially='DEFERRED'), nullable=False),
		sa.Column('deleted_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('archived_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
	)
	op.create_index('idx_portfolios_tenant', 'portfolios', ['tenant_id'])
	op.create_index('idx_portfolios_status', 'portfolios', ['status'])

	op.create_table(
		'portfolio_access',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('portfolio_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('portfolios.id', ondelete='CASCADE'), nullable=False),
		sa.Column('subject_type', sa.String(20), nullable=False),
		sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
		sa.Column('allow_view', sa.Boolean, server_default='true'),
		sa.Column('allow_download', sa.Boolean, server_default='false'),
		sa.Column('allow_print', sa.Boolean, server_default='false'),
		sa.Column('allow_edit', sa.Boolean, server_default='false'),
		sa.Column('allow_share', sa.Boolean, server_default='false'),
		sa.Column('inherit_to_cases', sa.Boolean, server_default='true'),
		sa.Column('valid_from', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('valid_until', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.UniqueConstraint('portfolio_id', 'subject_type', 'subject_id', name='uq_portfolio_subject_access'),
	)
	op.create_index('idx_portfolio_access_subject', 'portfolio_access', ['subject_type', 'subject_id'])

	# Cases
	op.create_table(
		'cases',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('case_number', sa.String(100), nullable=False),
		sa.Column('title', sa.String(500), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('status', sa.String(20), server_default='open'),
		sa.Column('opened_date', sa.Date),
		sa.Column('closed_date', sa.Date),
		sa.Column('due_date', sa.Date),
		sa.Column('case_type', sa.String(100)),
		sa.Column('jurisdiction', sa.String(100)),
		sa.Column('matter_id', sa.String(100)),
		sa.Column('portfolio_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('portfolios.id', ondelete='SET NULL')),
		sa.Column('metadata', postgresql.JSONB),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('deleted_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('archived_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT', deferrable=True, initially='DEFERRED'), nullable=False),
		sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT', deferrable=True, initially='DEFERRED'), nullable=False),
		sa.Column('deleted_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('archived_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.UniqueConstraint('tenant_id', 'case_number', name='uq_case_number'),
	)
	op.create_index('idx_cases_tenant', 'cases', ['tenant_id'])
	op.create_index('idx_cases_portfolio', 'cases', ['portfolio_id'])
	op.create_index('idx_cases_status', 'cases', ['status'])

	op.create_table(
		'case_documents',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('added_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('added_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.UniqueConstraint('case_id', 'document_id', name='uq_case_document'),
	)

	op.create_table(
		'case_access',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
		sa.Column('subject_type', sa.String(20), nullable=False),
		sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
		sa.Column('allow_view', sa.Boolean, server_default='true'),
		sa.Column('allow_download', sa.Boolean, server_default='false'),
		sa.Column('allow_print', sa.Boolean, server_default='false'),
		sa.Column('allow_edit', sa.Boolean, server_default='false'),
		sa.Column('allow_share', sa.Boolean, server_default='false'),
		sa.Column('valid_from', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('valid_until', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.UniqueConstraint('case_id', 'subject_type', 'subject_id', name='uq_case_subject_access'),
	)
	op.create_index('idx_case_access_subject', 'case_access', ['subject_type', 'subject_id'])

	# Bundles
	op.create_table(
		'bundles',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('title', sa.String(255), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('bundle_number', sa.String(50)),
		sa.Column('status', sa.String(20), server_default='draft'),
		sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='SET NULL')),
		sa.Column('metadata', postgresql.JSONB),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('deleted_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('archived_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT', deferrable=True, initially='DEFERRED'), nullable=False),
		sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT', deferrable=True, initially='DEFERRED'), nullable=False),
		sa.Column('deleted_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('archived_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
	)
	op.create_index('idx_bundles_tenant', 'bundles', ['tenant_id'])
	op.create_index('idx_bundles_case', 'bundles', ['case_id'])

	op.create_table(
		'bundle_sections',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('bundle_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bundles.id', ondelete='CASCADE'), nullable=False),
		sa.Column('title', sa.String(255), nullable=False),
		sa.Column('sort_order', sa.Integer, nullable=False),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)

	op.create_table(
		'bundle_documents',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('bundle_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bundles.id', ondelete='CASCADE'), nullable=False),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('sort_order', sa.Integer, nullable=False),
		sa.Column('section_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('bundle_sections.id', ondelete='SET NULL')),
		sa.Column('display_title', sa.String(255)),
		sa.Column('exhibit_number', sa.String(50)),
		sa.Column('start_page', sa.Integer),
		sa.Column('end_page', sa.Integer),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.UniqueConstraint('bundle_id', 'document_id', name='uq_bundle_document'),
	)
	op.create_index('idx_bundle_documents_order', 'bundle_documents', ['bundle_id', 'sort_order'])

	# Workflows
	op.create_table(
		'workflows',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('category', sa.String(100)),
		sa.Column('trigger_type', sa.String(50), server_default='manual'),
		sa.Column('trigger_conditions', postgresql.JSONB),
		sa.Column('mode', sa.String(20), server_default='operational'),
		sa.Column('is_active', sa.Boolean, server_default='true'),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
	)
	op.create_index('idx_workflows_tenant_active', 'workflows', ['tenant_id', 'is_active'])

	op.create_table(
		'workflow_steps',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(100), nullable=False),
		sa.Column('step_type', sa.String(50), nullable=False),
		sa.Column('step_order', sa.Integer, nullable=False),
		sa.Column('assignee_type', sa.String(50)),
		sa.Column('assignee_id', postgresql.UUID(as_uuid=True)),
		sa.Column('assignee_expression', sa.String(255)),
		sa.Column('condition_expression', sa.Text),
		sa.Column('action_type', sa.String(50)),
		sa.Column('action_config', postgresql.JSONB),
		sa.Column('deadline_hours', sa.Integer),
		sa.Column('escalation_step_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_steps.id', ondelete='SET NULL')),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)

	op.create_table(
		'workflow_instances',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('current_step_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_steps.id', ondelete='SET NULL')),
		sa.Column('status', sa.String(50), server_default='pending'),
		sa.Column('started_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('initiated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('context', postgresql.JSONB),
	)
	op.create_index('idx_workflow_instances_status', 'workflow_instances', ['status'])
	op.create_index('idx_workflow_instances_document', 'workflow_instances', ['document_id'])

	op.create_table(
		'workflow_step_executions',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('instance_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_instances.id', ondelete='CASCADE'), nullable=False),
		sa.Column('step_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_steps.id', ondelete='CASCADE'), nullable=False),
		sa.Column('status', sa.String(50), server_default='pending'),
		sa.Column('assigned_to', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('started_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('deadline_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('action_taken', sa.String(50)),
		sa.Column('comments', sa.Text),
		sa.Column('attachments', postgresql.ARRAY(sa.String)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_step_executions_pending', 'workflow_step_executions', ['status', 'deadline_at'])

	# Routing
	op.create_table(
		'routing_rules',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('priority', sa.Integer, server_default='100'),
		sa.Column('conditions', postgresql.JSONB, nullable=False),
		sa.Column('destination_type', sa.String(50), nullable=False),
		sa.Column('destination_id', postgresql.UUID(as_uuid=True)),
		sa.Column('mode', sa.String(20), server_default='both'),
		sa.Column('is_active', sa.Boolean, server_default='true'),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
	)
	op.create_index('idx_routing_rules_active', 'routing_rules', ['tenant_id', 'is_active', 'priority'])

	op.create_table(
		'routing_logs',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('rule_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('routing_rules.id', ondelete='SET NULL')),
		sa.Column('matched', sa.Boolean, nullable=False),
		sa.Column('destination_type', sa.String(50)),
		sa.Column('destination_id', postgresql.UUID(as_uuid=True)),
		sa.Column('mode', sa.String(20), nullable=False),
		sa.Column('evaluated_conditions', postgresql.JSONB),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_routing_logs_document', 'routing_logs', ['document_id'])

	# Form Recognition
	op.create_table(
		'form_templates',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.Text),
		sa.Column('category', sa.String(100)),
		sa.Column('page_count', sa.Integer, server_default='1'),
		sa.Column('template_image_urls', postgresql.ARRAY(sa.String)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
	)
	op.create_index('idx_form_templates_tenant', 'form_templates', ['tenant_id'])

	op.create_table(
		'form_fields',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('template_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('form_templates.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(100), nullable=False),
		sa.Column('label', sa.String(255)),
		sa.Column('field_type', sa.String(50), nullable=False),
		sa.Column('page_number', sa.Integer, server_default='1'),
		sa.Column('x', sa.Float, nullable=False),
		sa.Column('y', sa.Float, nullable=False),
		sa.Column('width', sa.Float, nullable=False),
		sa.Column('height', sa.Float, nullable=False),
		sa.Column('required', sa.Boolean, server_default='false'),
		sa.Column('validation_regex', sa.String(255)),
		sa.Column('expected_format', sa.String(100)),
		sa.Column('linked_field_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('form_fields.id', ondelete='SET NULL')),
		sa.Column('link_type', sa.String(50)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)

	op.create_table(
		'form_extractions',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('template_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('form_templates.id', ondelete='SET NULL')),
		sa.Column('status', sa.String(50), server_default='pending'),
		sa.Column('confidence_score', sa.Float),
		sa.Column('extracted_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('reviewed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_form_extractions_document', 'form_extractions', ['document_id'])
	op.create_index('idx_form_extractions_status', 'form_extractions', ['status'])

	op.create_table(
		'extracted_field_values',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('extraction_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('form_extractions.id', ondelete='CASCADE'), nullable=False),
		sa.Column('field_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('form_fields.id', ondelete='SET NULL')),
		sa.Column('page_number', sa.Integer, nullable=False),
		sa.Column('field_name', sa.String(100), nullable=False),
		sa.Column('field_type', sa.String(50), nullable=False),
		sa.Column('text_value', sa.Text),
		sa.Column('boolean_value', sa.Boolean),
		sa.Column('date_value', sa.Date),
		sa.Column('number_value', sa.Numeric),
		sa.Column('image_url', sa.String(500)),
		sa.Column('confidence', sa.Float),
		sa.Column('needs_review', sa.Boolean, server_default='false'),
		sa.Column('x', sa.Float),
		sa.Column('y', sa.Float),
		sa.Column('width', sa.Float),
		sa.Column('height', sa.Float),
	)

	op.create_table(
		'signatures',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('person_name', sa.String(255)),
		sa.Column('image_url', sa.String(500), nullable=False),
		sa.Column('thumbnail_url', sa.String(500)),
		sa.Column('captured_from_document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='SET NULL')),
		sa.Column('captured_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('is_verified', sa.Boolean, server_default='false'),
		sa.Column('verified_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('verified_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_signatures_tenant', 'signatures', ['tenant_id'])
	op.create_index('idx_signatures_user', 'signatures', ['user_id'])

	# Encryption
	op.create_table(
		'key_encryption_keys',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('key_version', sa.Integer, server_default='1'),
		sa.Column('encrypted_kek', sa.LargeBinary, nullable=False),
		sa.Column('is_active', sa.Boolean, server_default='true'),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('rotated_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True)),
		sa.UniqueConstraint('tenant_id', 'key_version', name='uq_tenant_key_version'),
	)
	op.create_index('idx_kek_tenant_active', 'key_encryption_keys', ['tenant_id', 'is_active'])

	op.create_table(
		'document_encryption_keys',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('key_version', sa.Integer, server_default='1'),
		sa.Column('encrypted_key', sa.LargeBinary, nullable=False),
		sa.Column('key_algorithm', sa.String(50), server_default='AES-256-GCM'),
		sa.Column('kek_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('key_encryption_keys.id', ondelete='RESTRICT'), nullable=False),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('rotated_at', postgresql.TIMESTAMP(timezone=True)),
		sa.UniqueConstraint('document_id', 'key_version', name='uq_document_key_version'),
	)
	op.create_index('idx_dek_document', 'document_encryption_keys', ['document_id'])

	op.create_table(
		'hidden_document_access',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='CASCADE'), nullable=False),
		sa.Column('requested_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
		sa.Column('requested_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('reason', sa.Text, nullable=False),
		sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
		sa.Column('approved_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('status', sa.String(20), server_default='pending'),
		sa.Column('expires_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_hidden_access_document', 'hidden_document_access', ['document_id'])
	op.create_index('idx_hidden_access_status', 'hidden_document_access', ['status'])

	# Add hidden columns to nodes
	op.add_column('nodes', sa.Column('is_hidden', sa.Boolean, server_default='false'))
	op.add_column('nodes', sa.Column('hidden_at', postgresql.TIMESTAMP(timezone=True)))
	op.add_column('nodes', sa.Column('hidden_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')))
	op.add_column('nodes', sa.Column('hidden_reason', sa.Text))
	op.create_index('idx_hidden_docs', 'nodes', ['is_hidden'], postgresql_where=sa.text("is_hidden = true"))

	# Ingestion
	op.create_table(
		'ingestion_sources',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('source_type', sa.String(50), nullable=False),
		sa.Column('config', postgresql.JSONB, nullable=False),
		sa.Column('mode', sa.String(20), server_default='operational'),
		sa.Column('default_document_type_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('document_types.id', ondelete='SET NULL')),
		sa.Column('apply_ocr', sa.Boolean, server_default='true'),
		sa.Column('auto_route', sa.Boolean, server_default='true'),
		sa.Column('is_active', sa.Boolean, server_default='true'),
		sa.Column('last_checked_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
		sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
	)
	op.create_index('idx_ingestion_sources_tenant', 'ingestion_sources', ['tenant_id', 'is_active'])

	op.create_table(
		'ingestion_jobs',
		sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
		sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ingestion_sources.id', ondelete='CASCADE'), nullable=False),
		sa.Column('source_path', sa.String(1000)),
		sa.Column('source_metadata', postgresql.JSONB),
		sa.Column('status', sa.String(50), server_default='pending'),
		sa.Column('error_message', sa.Text),
		sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('nodes.id', ondelete='SET NULL')),
		sa.Column('started_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('completed_at', postgresql.TIMESTAMP(timezone=True)),
		sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now()),
	)
	op.create_index('idx_ingestion_jobs_source', 'ingestion_jobs', ['source_id'])
	op.create_index('idx_ingestion_jobs_status', 'ingestion_jobs', ['status'])

	# Note: user_preferences table already exists from core migration f9c92867b8a4


def downgrade() -> None:
	# Note: don't drop user_preferences - managed by core migrations
	op.drop_table('ingestion_jobs')
	op.drop_table('ingestion_sources')
	op.drop_index('idx_hidden_docs', 'nodes')
	op.drop_column('nodes', 'hidden_reason')
	op.drop_column('nodes', 'hidden_by')
	op.drop_column('nodes', 'hidden_at')
	op.drop_column('nodes', 'is_hidden')
	op.drop_table('hidden_document_access')
	op.drop_table('document_encryption_keys')
	op.drop_table('key_encryption_keys')
	op.drop_table('signatures')
	op.drop_table('extracted_field_values')
	op.drop_table('form_extractions')
	op.drop_table('form_fields')
	op.drop_table('form_templates')
	op.drop_table('routing_logs')
	op.drop_table('routing_rules')
	op.drop_table('workflow_step_executions')
	op.drop_table('workflow_instances')
	op.drop_table('workflow_steps')
	op.drop_table('workflows')
	op.drop_table('bundle_documents')
	op.drop_table('bundle_sections')
	op.drop_table('bundles')
	op.drop_table('case_access')
	op.drop_table('case_documents')
	op.drop_table('cases')
	op.drop_table('portfolio_access')
	op.drop_table('portfolios')
	op.drop_table('tenant_settings')
	op.drop_table('tenant_branding')
	op.drop_table('tenants')
