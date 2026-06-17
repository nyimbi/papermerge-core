"""darchiva: add scheduled_reports table

Revision ID: a1b2c3d4e5f6
Revises: fa71c2c795a9
Create Date: 2026-06-17 08:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "fa71c2c795a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		"scheduled_reports",
		sa.Column("id", sa.String(32), primary_key=True),
		sa.Column("name", sa.String(200), nullable=False),
		sa.Column("report_type", sa.String(50), nullable=False),
		sa.Column("schedule", sa.String(20), nullable=False),
		sa.Column("delivery_hour", sa.Integer(), nullable=False, server_default="8"),
		sa.Column("day_of_week", sa.Integer(), nullable=True),
		sa.Column("recipients", sa.Text(), nullable=False),
		sa.Column("format", sa.String(10), nullable=False, server_default="xlsx"),
		sa.Column("filters", sa.Text(), nullable=False, server_default="{}"),
		sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
		sa.Column("last_sent_at", sa.DateTime(), nullable=True),
		sa.Column("send_count", sa.Integer(), nullable=False, server_default="0"),
		sa.Column(
			"tenant_id",
			sa.UUID(as_uuid=True),
			sa.ForeignKey("tenants.id", ondelete="CASCADE"),
			nullable=False,
		),
		sa.Column(
			"created_by_id",
			sa.UUID(as_uuid=True),
			sa.ForeignKey("core_users.id", ondelete="SET NULL"),
			nullable=True,
		),
		sa.Column(
			"created_at",
			sa.DateTime(),
			nullable=False,
			server_default=sa.text("now()"),
		),
	)

	op.create_index(
		"ix_scheduled_reports_tenant", "scheduled_reports", ["tenant_id"]
	)
	op.create_index(
		"ix_scheduled_reports_active", "scheduled_reports", ["is_active"]
	)
	op.create_index(
		"ix_scheduled_reports_schedule", "scheduled_reports", ["schedule"]
	)


def downgrade() -> None:
	op.drop_index("ix_scheduled_reports_schedule", "scheduled_reports")
	op.drop_index("ix_scheduled_reports_active", "scheduled_reports")
	op.drop_index("ix_scheduled_reports_tenant", "scheduled_reports")
	op.drop_table("scheduled_reports")
