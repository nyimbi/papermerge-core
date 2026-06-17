"""Add approval_workflows and approval_steps tables

Revision ID: darchiva_approvals
Revises: fa71c2c795a9
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "darchiva_approvals"
down_revision: Union[str, None] = "fa71c2c795a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_workflows",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="in_review",
        ),
        sa.Column("created_by_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_approval_workflows_document_id", "approval_workflows", ["document_id"])
    op.create_index("ix_approval_workflows_tenant_id", "approval_workflows", ["tenant_id"])

    op.create_table(
        "approval_steps",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "workflow_id",
            sa.String(36),
            sa.ForeignKey("approval_workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("approver_user_id", sa.String(36), nullable=True),
        sa.Column("approver_email", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_approval_steps_workflow_id", "approval_steps", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_approval_steps_workflow_id", table_name="approval_steps")
    op.drop_table("approval_steps")
    op.drop_index("ix_approval_workflows_tenant_id", table_name="approval_workflows")
    op.drop_index("ix_approval_workflows_document_id", table_name="approval_workflows")
    op.drop_table("approval_workflows")
