# (c) Copyright Datacraft, 2026
"""Create quality rules, assessments, and issues tables.

Revision ID: d4rc_0016
Revises: d4rc_0015
Create Date: 2026-06-11
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision: str = 'd4rc_0016'
down_revision: Union[str, None] = 'd4rc_0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.create_table(
		'quality_rules',
		sa.Column('id', sa.UUID(), nullable=False),
		sa.Column('tenant_id', sa.UUID(), nullable=False),
		sa.Column('name', sa.String(255), nullable=False),
		sa.Column('description', sa.Text(), nullable=True),
		sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
		sa.Column('document_type_id', sa.UUID(), nullable=True),
		sa.Column('applies_to_all', sa.Boolean(), nullable=False, server_default='true'),
		sa.Column('metric', sa.String(50), nullable=False),
		sa.Column('operator', sa.String(20), nullable=False),
		sa.Column('threshold', sa.Float(), nullable=False),
		sa.Column('threshold_upper', sa.Float(), nullable=True),
		sa.Column('severity', sa.String(20), nullable=False, server_default='warning'),
		sa.Column('action', sa.String(20), nullable=False, server_default='flag'),
		sa.Column('message_template', sa.Text(), nullable=True),
		sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
		sa.Column('created_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column('updated_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
		sa.ForeignKeyConstraint(['document_type_id'], ['document_types.id'], ondelete='SET NULL'),
		sa.PrimaryKeyConstraint('id'),
	)
	op.create_index('idx_quality_rules_tenant_active', 'quality_rules', ['tenant_id', 'is_active'])
	op.create_index('idx_quality_rules_metric', 'quality_rules', ['metric'])

	op.create_table(
		'quality_assessments',
		sa.Column('id', sa.UUID(), nullable=False),
		sa.Column('document_id', sa.UUID(), nullable=False),
		sa.Column('page_number', sa.Integer(), nullable=True),
		sa.Column('quality_score', sa.Float(), nullable=False),
		sa.Column('passed', sa.Boolean(), nullable=False, server_default='true'),
		sa.Column('resolution_dpi', sa.Integer(), nullable=True),
		sa.Column('skew_angle', sa.Float(), nullable=True),
		sa.Column('brightness', sa.Float(), nullable=True),
		sa.Column('contrast', sa.Float(), nullable=True),
		sa.Column('sharpness', sa.Float(), nullable=True),
		sa.Column('noise_level', sa.Float(), nullable=True),
		sa.Column('blur_score', sa.Float(), nullable=True),
		sa.Column('ocr_confidence', sa.Float(), nullable=True),
		sa.Column('is_blank', sa.Boolean(), nullable=True),
		sa.Column('orientation', sa.Integer(), nullable=True),
		sa.Column('file_size_bytes', sa.Integer(), nullable=True),
		sa.Column('width_px', sa.Integer(), nullable=True),
		sa.Column('height_px', sa.Integer(), nullable=True),
		sa.Column('issue_count', sa.Integer(), nullable=False, server_default='0'),
		sa.Column('critical_issues', sa.Integer(), nullable=False, server_default='0'),
		sa.Column('assessed_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column('assessed_by', sa.String(100), nullable=True),
		sa.Column('assessment_version', sa.String(20), nullable=False, server_default='1.0'),
		sa.Column('raw_metrics', JSONB(), nullable=True),
		sa.ForeignKeyConstraint(['document_id'], ['nodes.id'], ondelete='CASCADE'),
		sa.PrimaryKeyConstraint('id'),
	)
	op.create_index('idx_assessment_document', 'quality_assessments', ['document_id'])
	op.create_index('idx_assessment_score', 'quality_assessments', ['quality_score'])
	op.create_index('idx_assessment_passed', 'quality_assessments', ['passed'])

	op.create_table(
		'quality_issues',
		sa.Column('id', sa.UUID(), nullable=False),
		sa.Column('assessment_id', sa.UUID(), nullable=False),
		sa.Column('document_id', sa.UUID(), nullable=False),
		sa.Column('page_number', sa.Integer(), nullable=True),
		sa.Column('rule_id', sa.UUID(), nullable=True),
		sa.Column('metric', sa.String(50), nullable=False),
		sa.Column('actual_value', sa.Float(), nullable=False),
		sa.Column('expected_value', sa.Float(), nullable=True),
		sa.Column('severity', sa.String(20), nullable=False),
		sa.Column('message', sa.Text(), nullable=False),
		sa.Column('status', sa.String(20), nullable=False, server_default='open'),
		sa.Column('resolved_at', TIMESTAMP(timezone=True), nullable=True),
		sa.Column('resolved_by', sa.UUID(), nullable=True),
		sa.Column('resolution_notes', sa.Text(), nullable=True),
		sa.Column('auto_fix_applied', sa.Boolean(), nullable=False, server_default='false'),
		sa.Column('auto_fix_result', sa.Text(), nullable=True),
		sa.Column('created_at', TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.ForeignKeyConstraint(['assessment_id'], ['quality_assessments.id'], ondelete='CASCADE'),
		sa.ForeignKeyConstraint(['document_id'], ['nodes.id'], ondelete='CASCADE'),
		sa.ForeignKeyConstraint(['rule_id'], ['quality_rules.id'], ondelete='SET NULL'),
		sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ondelete='SET NULL'),
		sa.PrimaryKeyConstraint('id'),
	)
	op.create_index('idx_issue_assessment', 'quality_issues', ['assessment_id'])
	op.create_index('idx_issue_document', 'quality_issues', ['document_id'])
	op.create_index('idx_issue_status', 'quality_issues', ['status'])
	op.create_index('idx_issue_severity', 'quality_issues', ['severity'])


def downgrade() -> None:
	op.drop_table('quality_issues')
	op.drop_table('quality_assessments')
	op.drop_table('quality_rules')
