# (c) Copyright Datacraft, 2026
"""ORM model for project-level RBAC membership."""
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


class ProjectMemberModel(Base):
	"""
	Maps a user to a scanning project with a specific role.

	Roles (highest to lowest): owner > supervisor > operator > viewer

	Design notes:
	  - No rows for a project = open-access (backwards compat with pre-RBAC data).
	  - invited_by_id / accepted_at are nullable — direct adds skip the invite flow.
	  - tenant_id is denormalised for fast tenant-scoped queries without a JOIN.
	"""
	__tablename__ = "project_members"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	project_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("scanning_projects.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	user_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("users.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	# "owner" | "supervisor" | "operator" | "viewer"
	role: Mapped[str] = mapped_column(String(20), nullable=False)
	invited_by_id: Mapped[str | None] = mapped_column(
		String(36),
		ForeignKey("users.id", ondelete="SET NULL"),
		nullable=True,
	)
	accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
	tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

	__table_args__ = (
		UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
	)
