"""add document_chat_messages table

Revision ID: a1b2c3d4e5f6
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_chat_messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('conversation_id', sa.String(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('page_references', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('created_by_id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column(
            'created_at',
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_document_chat_messages_conversation_id', 'document_chat_messages', ['conversation_id'])
    op.create_index('ix_document_chat_messages_document_id', 'document_chat_messages', ['document_id'])
    op.create_index('ix_document_chat_messages_tenant_id', 'document_chat_messages', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_document_chat_messages_tenant_id', table_name='document_chat_messages')
    op.drop_index('ix_document_chat_messages_document_id', table_name='document_chat_messages')
    op.drop_index('ix_document_chat_messages_conversation_id', table_name='document_chat_messages')
    op.drop_table('document_chat_messages')
