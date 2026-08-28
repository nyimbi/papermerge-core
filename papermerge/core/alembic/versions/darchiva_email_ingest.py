"""add email_ingest_configs table

Revision ID: 763584d70dbf
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '763584d70dbf'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_ingest_configs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('host', sa.String(), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False, server_default='993'),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('encrypted_password', sa.Text(), nullable=False),
        sa.Column('use_ssl', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('mailbox_folder', sa.String(), nullable=False, server_default='INBOX'),
        sa.Column('last_processed_uid', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('destination_folder_id', sa.String(), nullable=True),
        sa.Column('project_id', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('check_interval_minutes', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('allowed_senders', sa.Text(), nullable=False, server_default=''),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('created_by_id', sa.String(), nullable=False),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column('last_checked_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('documents_ingested', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_email_ingest_configs_tenant_id',
        'email_ingest_configs',
        ['tenant_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_email_ingest_configs_tenant_id', table_name='email_ingest_configs')
    op.drop_table('email_ingest_configs')
