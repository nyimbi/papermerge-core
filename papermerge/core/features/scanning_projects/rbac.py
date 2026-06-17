# (c) Copyright Datacraft, 2026
"""Project-level RBAC helpers for scanning projects."""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .db.orm_members import ProjectMemberModel

# Ordered lowest → highest; higher index = more privilege.
ROLE_HIERARCHY: list[str] = ["viewer", "operator", "supervisor", "owner"]


def _role_rank(role: str) -> int:
	"""Return numeric rank for a role; -1 if unknown."""
	try:
		return ROLE_HIERARCHY.index(role)
	except ValueError:
		return -1


async def check_project_access(
	project_id: str,
	user_id: str,
	required_role: str,
	session: AsyncSession,
) -> bool:
	"""
	Return True if *user_id* has *required_role* or higher on *project_id*.

	Backwards-compatibility rule: if the project has **no** ProjectMember rows
	at all, access is granted to everyone (open-access mode for pre-RBAC data).

	Args:
		project_id: UUID string of the scanning project.
		user_id:    UUID string of the requesting user.
		required_role: One of "viewer" | "operator" | "supervisor" | "owner".
		session:    Active async SQLAlchemy session.

	Returns:
		True  — user is allowed.
		False — user is explicitly excluded or has insufficient role.
	"""
	# Count total members for this project (open-access check).
	count_stmt = (
		select(func.count())
		.select_from(ProjectMemberModel)
		.where(ProjectMemberModel.project_id == project_id)
	)
	total: int = (await session.execute(count_stmt)).scalar_one()
	if total == 0:
		# No RBAC configured — open access.
		return True

	# Fetch the specific membership row for this user.
	member_stmt = (
		select(ProjectMemberModel.role)
		.where(
			ProjectMemberModel.project_id == project_id,
			ProjectMemberModel.user_id == user_id,
		)
	)
	row = (await session.execute(member_stmt)).first()
	if row is None:
		# Project has members but this user is not one of them.
		return False

	user_rank = _role_rank(row[0])
	required_rank = _role_rank(required_role)
	return user_rank >= required_rank
