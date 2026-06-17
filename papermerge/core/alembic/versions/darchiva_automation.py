"""Create automation_rules table.

Revision ID: darchiva_automation
Revises: darchiva_webhook_delivery_status
Create Date: 2026-06-17

"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "darchiva_automation"
down_revision: Union[str, None] = "darchiva_webhook_delivery_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("trigger_event", sa.String(64), nullable=False),
        sa.Column("conditions", sa.Text, nullable=False, server_default="'[]'"),
        sa.Column("actions", sa.Text, nullable=False, server_default="'[]'"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_automation_rules_tenant_id", "automation_rules", ["tenant_id"])
    op.create_index("ix_automation_rules_trigger_event", "automation_rules", ["trigger_event"])


def downgrade() -> None:
    op.drop_index("ix_automation_rules_trigger_event", table_name="automation_rules")
    op.drop_index("ix_automation_rules_tenant_id", table_name="automation_rules")
    op.drop_table("automation_rules")
