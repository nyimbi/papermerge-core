"""Add data_export_jobs table for GDPR export and document bundles

Revision ID: 3bfd98961f2e
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3bfd98961f2e'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		'data_export_jobs',
		sa.Column('id', sa.String(36), nullable=False),
		sa.Column('job_type', sa.String(32), nullable=False),
		sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
		sa.Column('requested_by_id', sa.String(36), nullable=False),
		sa.Column('tenant_id', sa.String(36), nullable=False),
		sa.Column('params', sa.Text(), nullable=False, server_default='{}'),
		sa.Column('file_path', sa.Text(), nullable=True),
		sa.Column('file_size_bytes', sa.Integer(), nullable=True),
		sa.Column('error_message', sa.Text(), nullable=True),
		sa.Column(
			'created_at',
			sa.TIMESTAMP(timezone=True),
			nullable=False,
			server_default=sa.text('now()'),
		),
		sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
		sa.PrimaryKeyConstraint('id'),
	)
	op.create_index('ix_data_export_jobs_tenant_id', 'data_export_jobs', ['tenant_id'])
	op.create_index('ix_data_export_jobs_requested_by_id', 'data_export_jobs', ['requested_by_id'])


def downgrade() -> None:
	op.drop_index('ix_data_export_jobs_requested_by_id', table_name='data_export_jobs')
	op.drop_index('ix_data_export_jobs_tenant_id', table_name='data_export_jobs')
	op.drop_table('data_export_jobs')
