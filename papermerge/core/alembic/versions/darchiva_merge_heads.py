"""Merge d4rc_0018 and darchiva_user_sessions heads.

Revision ID: darchiva_merge_heads
Revises: d4rc_0018, darchiva_user_sessions
Create Date: 2026-06-13
"""
from typing import Union

from alembic import op

revision: str = "darchiva_merge_heads"
down_revision: Union[tuple, None] = ("d4rc_0018", "darchiva_user_sessions")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
