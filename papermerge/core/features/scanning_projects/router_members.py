# (c) Copyright Datacraft, 2026
"""FastAPI router — project-level RBAC membership endpoints.

Auto-discovered alongside router.py by the application factory that mounts
all scanning-projects routers under /scanning-projects.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.schema import User

from .db.orm_members import ProjectMemberModel

try:
	from uuid6 import uuid7
	def _new_id() -> str:
		return str(uuid7())
except ImportError:
	import uuid
	def _new_id() -> str:
		return str(uuid.uuid4())


router = APIRouter(prefix="/scanning-projects", tags=["scanning-projects-members"])

VALID_ROLES = {"owner", "supervisor", "operator", "viewer"}


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class MemberOut(BaseModel):
	id: str
	project_id: str
	user_id: str
	role: str
	invited_by_id: str | None = None
	accepted_at: str | None = None
	tenant_id: str
	created_at: str
	# denormed user info — populated from join
	email: str | None = None
	username: str | None = None

	model_config = {"from_attributes": True}


class AddMemberBody(BaseModel):
	user_id: str
	role: str


class UpdateRoleBody(BaseModel):
	role: str


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _validate_role(role: str) -> None:
	if role not in VALID_ROLES:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail=f"role must be one of {sorted(VALID_ROLES)}",
		)


async def _get_member_or_404(
	session: AsyncSession,
	project_id: str,
	member_id: str,
) -> ProjectMemberModel:
	stmt = select(ProjectMemberModel).where(
		ProjectMemberModel.id == member_id,
		ProjectMemberModel.project_id == project_id,
	)
	row = (await session.execute(stmt)).scalar_one_or_none()
	if row is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
	return row


def _to_out(m: ProjectMemberModel, email: str | None = None, username: str | None = None) -> MemberOut:
	return MemberOut(
		id=m.id,
		project_id=m.project_id,
		user_id=m.user_id,
		role=m.role,
		invited_by_id=m.invited_by_id,
		accepted_at=m.accepted_at.isoformat() if m.accepted_at else None,
		tenant_id=m.tenant_id,
		created_at=m.created_at.isoformat(),
		email=email,
		username=username,
	)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/{project_id}/members", response_model=list[MemberOut])
async def list_members(
	project_id: str,
	current_user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[MemberOut]:
	"""List all members of a project with joined user info."""
	from sqlalchemy import text

	# Join with users table to pull email + username in one query.
	stmt = text("""
		SELECT
			pm.id, pm.project_id, pm.user_id, pm.role,
			pm.invited_by_id, pm.accepted_at, pm.tenant_id, pm.created_at,
			u.email, u.username
		FROM project_members pm
		LEFT JOIN users u ON u.id = pm.user_id
		WHERE pm.project_id = :project_id
		ORDER BY pm.created_at
	""")
	rows = (await session.execute(stmt, {"project_id": project_id})).mappings().all()

	return [
		MemberOut(
			id=r["id"],
			project_id=r["project_id"],
			user_id=r["user_id"],
			role=r["role"],
			invited_by_id=r["invited_by_id"],
			accepted_at=r["accepted_at"].isoformat() if r["accepted_at"] else None,
			tenant_id=r["tenant_id"],
			created_at=r["created_at"].isoformat(),
			email=r["email"],
			username=r["username"],
		)
		for r in rows
	]


@router.post(
	"/{project_id}/members",
	response_model=MemberOut,
	status_code=status.HTTP_201_CREATED,
)
async def add_member(
	project_id: str,
	body: AddMemberBody,
	current_user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> MemberOut:
	"""Add a user to a project with the given role."""
	_validate_role(body.role)

	# Check for duplicate.
	exists_stmt = select(ProjectMemberModel).where(
		ProjectMemberModel.project_id == project_id,
		ProjectMemberModel.user_id == body.user_id,
	)
	if (await session.execute(exists_stmt)).scalar_one_or_none() is not None:
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail="User is already a member of this project",
		)

	member = ProjectMemberModel(
		id=_new_id(),
		project_id=project_id,
		user_id=body.user_id,
		role=body.role,
		invited_by_id=str(current_user.id),
		tenant_id=str(current_user.tenant_id),
	)
	session.add(member)
	await session.commit()
	await session.refresh(member)
	return _to_out(member)


@router.patch("/{project_id}/members/{member_id}", response_model=MemberOut)
async def update_member_role(
	project_id: str,
	member_id: str,
	body: UpdateRoleBody,
	current_user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> MemberOut:
	"""Change the role of an existing project member."""
	_validate_role(body.role)
	member = await _get_member_or_404(session, project_id, member_id)
	member.role = body.role
	await session.commit()
	await session.refresh(member)
	return _to_out(member)


@router.delete("/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
	project_id: str,
	member_id: str,
	current_user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Remove a member from a project."""
	member = await _get_member_or_404(session, project_id, member_id)
	await session.delete(member)
	await session.commit()
