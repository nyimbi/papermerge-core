"""add auto_routing_rules table

Revision ID: darchiva_auto_routing
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

# revision identifiers, used by Alembic.
revision: str = 'darchiva_auto_routing'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'auto_routing_rules',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('document_type', sa.String(100), nullable=False),
        sa.Column('confidence_threshold', sa.Float, nullable=False, server_default='0.75'),
        sa.Column(
            'destination_folder_id',
            UUID(as_uuid=True),
            sa.ForeignKey('nodes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'project_id',
            UUID(as_uuid=True),
            sa.ForeignKey('nodes.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('priority', sa.Integer, nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('applied_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column(
            'tenant_id',
            UUID(as_uuid=True),
            sa.ForeignKey('tenants.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'created_by_id',
            UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'updated_at',
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )

    op.create_index(
        'idx_auto_routing_rules_tenant_active_priority',
        'auto_routing_rules',
        ['tenant_id', 'is_active', 'priority'],
    )
    op.create_index(
        'idx_auto_routing_rules_document_type',
        'auto_routing_rules',
        ['tenant_id', 'document_type', 'is_active'],
    )
    # General tenant lookup index
    op.create_index(
        'idx_auto_routing_rules_tenant_id',
        'auto_routing_rules',
        ['tenant_id'],
    )


def downgrade() -> None:
    op.drop_index('idx_auto_routing_rules_tenant_id', table_name='auto_routing_rules')
    op.drop_index('idx_auto_routing_rules_document_type', table_name='auto_routing_rules')
    op.drop_index('idx_auto_routing_rules_tenant_active_priority', table_name='auto_routing_rules')
    op.drop_table('auto_routing_rules')
