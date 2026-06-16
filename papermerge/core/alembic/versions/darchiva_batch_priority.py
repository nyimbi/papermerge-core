"""add priority column to scanning_batches

Revision ID: darchiva_batch_priority
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'darchiva_batch_priority'
down_revision: Union[str, None] = 'fa71c2c795a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'scanning_batches',
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index(
        'ix_scanning_batches_priority',
        'scanning_batches',
        ['priority'],
    )


def downgrade() -> None:
    op.drop_index('ix_scanning_batches_priority', table_name='scanning_batches')
    op.drop_column('scanning_batches', 'priority')
