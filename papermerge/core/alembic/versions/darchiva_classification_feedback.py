"""add classification feedback table

Revision ID: a1b2c3d4e5f6
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'classification_feedback',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('predicted_type', sa.String(255), nullable=True),
        sa.Column('predicted_confidence', sa.Float(), nullable=True),
        sa.Column('corrected_type', sa.String(255), nullable=False),
        sa.Column('feedback_by_id', sa.String(255), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('created_at', TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['nodes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_clf_feedback_document', 'classification_feedback', ['document_id'])
    op.create_index('idx_clf_feedback_tenant', 'classification_feedback', ['tenant_id'])
    op.create_index('idx_clf_feedback_corrected_type', 'classification_feedback', ['corrected_type'])


def downgrade() -> None:
    op.drop_index('idx_clf_feedback_corrected_type', table_name='classification_feedback')
    op.drop_index('idx_clf_feedback_tenant', table_name='classification_feedback')
    op.drop_index('idx_clf_feedback_document', table_name='classification_feedback')
    op.drop_table('classification_feedback')
