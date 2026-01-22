# (c) Copyright Datacraft, 2026
"""Rename metadata columns to avoid SQLAlchemy reserved attribute name.

Revision ID: d4rc_0008
Revises: d4rc_0007
Create Date: 2026-01-22

"""
from typing import Sequence, Union
from alembic import op


revision: str = 'd4rc_0008'
down_revision: Union[str, None] = 'd4rc_0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	# Rename metadata column in cases table to case_metadata
	op.alter_column('cases', 'metadata', new_column_name='case_metadata')

	# Rename metadata column in bundles table to bundle_metadata
	op.alter_column('bundles', 'metadata', new_column_name='bundle_metadata')

	# Rename metadata column in portfolios table to portfolio_metadata
	op.alter_column('portfolios', 'metadata', new_column_name='portfolio_metadata')


def downgrade() -> None:
	# Rename back to metadata
	op.alter_column('cases', 'case_metadata', new_column_name='metadata')
	op.alter_column('bundles', 'bundle_metadata', new_column_name='metadata')
	op.alter_column('portfolios', 'portfolio_metadata', new_column_name='metadata')
