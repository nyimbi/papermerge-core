"""Add tenant_id to quality_assessments for multi-tenant isolation.

Revision ID: d4rc_0018
Revises: d4rc_0017
Create Date: 2026-06-11
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "d4rc_0018"
down_revision: Union[str, None] = "d4rc_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quality_assessments",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_quality_assessments_tenant",
        "quality_assessments",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "idx_quality_assessments_tenant",
        "quality_assessments",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_quality_assessments_tenant", "quality_assessments")
    op.drop_constraint(
        "fk_quality_assessments_tenant", "quality_assessments", type_="foreignkey"
    )
    op.drop_column("quality_assessments", "tenant_id")
