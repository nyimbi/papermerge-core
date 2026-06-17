"""dArchiva digital signature requests

Revision ID: darchiva_signatures
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'darchiva_signatures'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_signature_requests',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
        ),
        sa.Column('document_id', sa.String(64), nullable=False),
        sa.Column('requested_from_email', sa.String(255), nullable=False),
        sa.Column('requested_from_name', sa.String(255), nullable=False, server_default=''),
        sa.Column('requested_by_id', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('signed_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('declined_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('decline_reason', sa.Text(), nullable=True),
        sa.Column('signature_data', sa.Text(), nullable=True),
        sa.Column('signature_page', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('signature_x', sa.Float(), nullable=False, server_default='0.7'),
        sa.Column('signature_y', sa.Float(), nullable=False, server_default='0.85'),
        sa.Column('signature_width', sa.Float(), nullable=False, server_default='0.25'),
        sa.Column('signature_height', sa.Float(), nullable=False, server_default='0.1'),
        sa.Column('signed_document_id', sa.String(64), nullable=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column(
            'created_at',
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )

    op.create_index(
        'idx_sig_req_document', 'document_signature_requests', ['document_id']
    )
    op.create_index(
        'idx_sig_req_status', 'document_signature_requests', ['status']
    )
    op.create_index(
        'idx_sig_req_tenant', 'document_signature_requests', ['tenant_id']
    )
    op.create_index(
        'idx_sig_req_requested_by', 'document_signature_requests', ['requested_by_id']
    )


def downgrade() -> None:
    op.drop_index('idx_sig_req_requested_by', table_name='document_signature_requests')
    op.drop_index('idx_sig_req_tenant', table_name='document_signature_requests')
    op.drop_index('idx_sig_req_status', table_name='document_signature_requests')
    op.drop_index('idx_sig_req_document', table_name='document_signature_requests')
    op.drop_table('document_signature_requests')
