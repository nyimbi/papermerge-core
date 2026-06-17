"""Add project_members table for project-level RBAC.

Revision ID: darchiva_project_members
Revises: darchiva_exception_supervisor_tables
Create Date: 2026-06-17

"""
from alembic import op
import sqlalchemy as sa

revision = "darchiva_project_members"
down_revision = "darchiva_exception_supervisor_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.create_table(
		"project_members",
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column(
			"project_id",
			sa.String(36),
			sa.ForeignKey("scanning_projects.id", ondelete="CASCADE"),
			nullable=False,
			index=True,
		),
		sa.Column(
			"user_id",
			sa.String(36),
			sa.ForeignKey("users.id", ondelete="CASCADE"),
			nullable=False,
			index=True,
		),
		sa.Column("role", sa.String(20), nullable=False),
		sa.Column(
			"invited_by_id",
			sa.String(36),
			sa.ForeignKey("users.id", ondelete="SET NULL"),
			nullable=True,
		),
		sa.Column("accepted_at", sa.DateTime, nullable=True),
		sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
		sa.Column(
			"created_at",
			sa.DateTime,
			server_default=sa.func.now(),
			nullable=False,
		),
	)
	op.create_unique_constraint(
		"uq_project_members_project_user",
		"project_members",
		["project_id", "user_id"],
	)
	op.create_index("idx_project_members_role", "project_members", ["role"])


def downgrade() -> None:
	op.drop_index("idx_project_members_role", table_name="project_members")
	op.drop_constraint(
		"uq_project_members_project_user",
		"project_members",
		type_="unique",
	)
	op.drop_table("project_members")
