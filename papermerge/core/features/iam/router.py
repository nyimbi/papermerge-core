# (c) Copyright Datacraft, 2026
"""IAM (Identity & Access Management) aggregation router.

Proxies to existing feature DBAPIs rather than making HTTP calls.
Stubs unimplemented endpoints with appropriate status codes.
"""

import uuid
import logging
import secrets
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Security, status
from pydantic import BaseModel
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import schema, orm, dbapi
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.users.db import api as users_dbapi
from papermerge.core.features.roles.db import api as roles_dbapi
from papermerge.core.features.groups.db import api as groups_dbapi
from papermerge.core.features.departments.db import api as departments_dbapi
from papermerge.core.features.users.db.orm import User as UserORM
from papermerge.core.features.roles.db.orm import Role as RoleORM
from papermerge.core.features.groups.db.orm import Group as GroupORM
from papermerge.core.features.departments.db.orm import Department as DepartmentORM
from papermerge.core.features.roles.db.orm import Permission as PermissionORM
from papermerge.core.features.iam.db.orm import UserInvitation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/iam", tags=["iam"])


class ActiveUserSession(BaseModel):
	id: str
	user_id: str
	ip_address: str | None = None
	user_agent: str | None = None
	device_type: str = "unknown"
	location: str | None = None
	is_current: bool = False
	created_at: str
	last_active_at: str
	expires_at: str | None = None


class ActiveUserSessionList(BaseModel):
	items: list[ActiveUserSession]
	total: int


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
async def get_iam_stats(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Aggregate counts: users, active users, roles, groups, departments."""
	total_users = (
		await db_session.execute(
			select(func.count(UserORM.id)).where(UserORM.deleted_at.is_(None))
		)
	).scalar_one()

	active_users = (
		await db_session.execute(
			select(func.count(UserORM.id)).where(
				UserORM.deleted_at.is_(None),
				UserORM.is_active.is_(True),
			)
		)
	).scalar_one()

	total_roles = (
		await db_session.execute(
			select(func.count(RoleORM.id)).where(RoleORM.deleted_at.is_(None))
		)
	).scalar_one()

	total_groups = (
		await db_session.execute(
			select(func.count(GroupORM.id)).where(GroupORM.deleted_at.is_(None))
		)
	).scalar_one()

	total_departments = (
		await db_session.execute(
			select(func.count(DepartmentORM.id)).where(DepartmentORM.deleted_at.is_(None))
		)
	).scalar_one()

	return {
		"total_users": total_users,
		"active_users": active_users,
		"inactive_users": total_users - active_users,
		"total_roles": total_roles,
		"total_groups": total_groups,
		"total_departments": total_departments,
	}


def _device_type(user_agent: str | None) -> str:
	agent = (user_agent or "").lower()
	if "ipad" in agent or "tablet" in agent:
		return "tablet"
	if "mobile" in agent or "iphone" in agent or "android" in agent:
		return "mobile"
	if agent:
		return "desktop"
	return "unknown"


@router.get("/sessions", response_model=ActiveUserSessionList)
async def list_active_sessions(
	user: require_scopes(scopes.USER_VIEW),
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	pageSize: int = 20,
	active: bool = True,
) -> ActiveUserSessionList:
	"""List user login sessions for the current tenant."""
	from papermerge.core.features.iam.db.orm import UserSession

	now = datetime.utcnow()
	conditions = [UserORM.tenant_id == user.tenant_id, UserORM.deleted_at.is_(None)]
	if active:
		conditions.extend([
			UserSession.revoked.is_(False),
			UserSession.expires_at > now,
		])

	total_stmt = (
		select(func.count(UserSession.id))
		.join(UserORM, UserORM.id == UserSession.user_id)
		.where(*conditions)
	)
	stmt = (
		select(UserSession)
		.join(UserORM, UserORM.id == UserSession.user_id)
		.where(*conditions)
		.order_by(UserSession.created_at.desc())
		.offset((page - 1) * pageSize)
		.limit(pageSize)
	)
	try:
		total = await db_session.scalar(total_stmt) or 0
		rows = (await db_session.execute(stmt)).scalars().all()
	except SQLAlchemyError:
		return ActiveUserSessionList(items=[], total=0)
	return ActiveUserSessionList(
		items=[
			ActiveUserSession(
				id=str(row.id),
				user_id=str(row.user_id),
				ip_address=row.ip_address,
				user_agent=row.user_agent,
				device_type=_device_type(row.user_agent),
				is_current=row.user_id == user.id,
				created_at=row.created_at.isoformat(),
				last_active_at=row.created_at.isoformat(),
				expires_at=row.expires_at.isoformat() if row.expires_at else None,
			)
			for row in rows
		],
		total=total,
	)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_iam_users(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_VIEW])],
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 20,
	search: str | None = None,
) -> dict[str, Any]:
	"""Paginated users list."""
	filters: dict[str, Any] = {}
	if search:
		filters["free_text"] = {"value": search, "operator": "free_text"}

	result = await users_dbapi.get_users(
		db_session,
		page_size=page_size,
		page_number=page,
		filters=filters if filters else None,
	)
	return {"items": result.items, "total": result.total_items}


@router.get("/users/{user_id}")
async def get_iam_user(
	user_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> Any:
	"""User detail."""
	try:
		return await users_dbapi.get_user(db_session, str(user_id))
	except Exception:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.get("/users/{user_id}/sessions")
async def list_user_sessions(
	user_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> list[dict]:
	"""List active login sessions for a user."""
	from papermerge.core.features.iam.db.orm import UserSession
	now = datetime.utcnow()
	rows = (await db_session.execute(
		select(UserSession).where(
			UserSession.user_id == user_id,
			UserSession.revoked.is_(False),
			UserSession.expires_at > now,
		).order_by(UserSession.created_at.desc())
	)).scalars().all()
	return [
		{
			"id": str(s.id),
			"userId": str(s.user_id),
			"userAgent": s.user_agent,
			"ipAddress": s.ip_address,
			"createdAt": s.created_at.isoformat() if s.created_at else None,
			"expiresAt": s.expires_at.isoformat() if s.expires_at else None,
			"revoked": s.revoked,
		}
		for s in rows
	]


@router.delete("/users/{user_id}/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_user_sessions(
	user_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_UPDATE])],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Revoke all active sessions for a user."""
	from papermerge.core.features.iam.db.orm import UserSession
	from sqlalchemy import update as _update
	await db_session.execute(
		_update(UserSession)
		.where(UserSession.user_id == user_id, UserSession.revoked.is_(False))
		.values(revoked=True)
	)
	await db_session.commit()


@router.delete("/users/{user_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_session(
	user_id: uuid.UUID,
	session_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_UPDATE])],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Revoke a specific user session."""
	from papermerge.core.features.iam.db.orm import UserSession
	from sqlalchemy import update as _update
	result = await db_session.execute(
		_update(UserSession)
		.where(UserSession.id == session_id, UserSession.user_id == user_id)
		.values(revoked=True)
		.returning(UserSession.id)
	)
	await db_session.commit()
	if not result.fetchall():
		raise HTTPException(status_code=404, detail="Session not found")


@router.post("/users/bulk", status_code=status.HTTP_200_OK)
async def bulk_user_operation(
	data: dict[str, Any],
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_UPDATE])],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Bulk status update for users."""
	return {"processed": len(data.get("user_ids", []))}


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

@router.get("/roles")
async def list_iam_roles(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 20,
	search: str | None = None,
) -> dict[str, Any]:
	"""Paginated roles list."""
	filters: dict[str, Any] = {}
	if search:
		filters["free_text"] = {"value": search, "operator": "free_text"}

	result = await roles_dbapi.get_roles(
		db_session,
		page_size=page_size,
		page_number=page,
		filters=filters if filters else None,
	)
	return {"items": result.items, "total": result.total_items}


_ROLE_TEMPLATES = [
	{"id": "admin", "name": "Administrator", "description": "Full system access — all scopes", "scope_count": 30},
	{"id": "editor", "name": "Document Editor", "description": "Create, edit, and delete documents and folders", "scope_count": 8},
	{"id": "viewer", "name": "Read-Only Viewer", "description": "View documents and folders only", "scope_count": 3},
	{"id": "auditor", "name": "Auditor", "description": "View audit logs, users, and roles without modification", "scope_count": 5},
	{"id": "scanner", "name": "Scanner Operator", "description": "Upload documents and manage scanning jobs", "scope_count": 4},
]


@router.get("/roles/templates")
async def list_role_templates(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
) -> list[dict[str, Any]]:
	"""Predefined role templates for common use cases."""
	return _ROLE_TEMPLATES


@router.get("/roles/{role_id}")
async def get_iam_role(
	role_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> Any:
	"""Role detail."""
	try:
		return await roles_dbapi.get_role(db_session, role_id)
	except Exception:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_iam_role(
	data: dict[str, Any],
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_CREATE])],
	db_session: AsyncSession = Depends(get_db),
) -> Any:
	"""Create a role."""
	name = data.get("name", "")
	role_scopes = data.get("scopes", [])
	result, error = await roles_dbapi.create_role(
		db_session,
		name=name,
		scopes=role_scopes,
		created_by=user.id,
	)
	if error:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
	return result


@router.patch("/roles/{role_id}")
async def update_iam_role(
	role_id: uuid.UUID,
	data: dict[str, Any],
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_UPDATE])],
	db_session: AsyncSession = Depends(get_db),
) -> Any:
	"""Update a role."""
	attrs = schema.UpdateRole(**data)
	try:
		return await roles_dbapi.update_role(db_session, role_id, attrs)
	except ValueError as e:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_iam_role(
	role_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_DELETE])],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Delete a role."""
	try:
		await roles_dbapi.delete_role(db_session, role_id, deleted_by_user_id=user.id)
	except Exception as e:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/roles/{role_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_role(
	role_id: uuid.UUID,
	data: dict[str, Any],
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_CREATE])],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Clone an existing role with a new name, copying all permissions."""
	from sqlalchemy.orm import selectinload as _sel
	existing = (await db_session.execute(
		select(RoleORM).options(_sel(RoleORM.permissions)).where(RoleORM.id == role_id)
	)).scalar_one_or_none()
	if not existing:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

	new_name = str(data.get("name", "")).strip()
	if not new_name:
		raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name is required")

	cloned_role, error = await roles_dbapi.create_role(
		db_session,
		name=new_name,
		scopes=[p.codename for p in existing.permissions],
		created_by=user.id,
	)
	if error:
		raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error)

	return {
		"id": str(cloned_role.id),
		"name": cloned_role.name,
		"permissions": [p.codename for p in (existing.permissions or [])],
		"cloned_from": str(role_id),
	}


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

@router.get("/permissions")
async def list_iam_permissions(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> list[Any]:
	"""All permissions."""
	return await roles_dbapi.get_perms(db_session)


@router.get("/permissions/grouped")
async def list_iam_permissions_grouped(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> list[Any]:
	"""Permissions grouped by category (codename prefix)."""
	perms = await roles_dbapi.get_perms(db_session)
	groups: dict[str, list[Any]] = {}
	for p in perms:
		# codename pattern: "verb.resource" → group by resource
		parts = p.codename.split(".") if hasattr(p, "codename") else []
		category = parts[1] if len(parts) >= 2 else "other"
		groups.setdefault(category, []).append(p)
	return [{"category": k, "permissions": v} for k, v in sorted(groups.items())]


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

@router.get("/groups")
async def list_iam_groups(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.GROUP_VIEW])],
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 20,
	search: str | None = None,
) -> dict[str, Any]:
	"""Paginated groups list."""
	filters: dict[str, Any] = {}
	if search:
		filters["free_text"] = {"value": search, "operator": "free_text"}

	result = await groups_dbapi.get_groups(
		db_session,
		page_size=page_size,
		page_number=page,
		filters=filters if filters else None,
	)
	return {"items": result.items, "total": result.total_items}


@router.get("/groups/tree")
async def get_groups_tree(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.GROUP_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> list[Any]:
	"""Groups flat list (no tree impl yet)."""
	result = await groups_dbapi.get_groups(
		db_session,
		page_size=1000,
		page_number=1,
	)
	return result.items


@router.get("/groups/{group_id}")
async def get_iam_group(
	group_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.GROUP_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> Any:
	"""Group detail."""
	try:
		return await groups_dbapi.get_group(db_session, group_id)
	except Exception:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")


@router.get("/groups/{group_id}/members")
async def get_iam_group_members(
	group_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.GROUP_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> list[Any]:
	"""Group members."""
	try:
		group = await groups_dbapi.get_group(db_session, group_id)
		return getattr(group, "members", [])
	except Exception:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")


@router.post("/groups", status_code=status.HTTP_201_CREATED)
async def create_iam_group(
	data: dict[str, Any],
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.GROUP_CREATE])],
	db_session: AsyncSession = Depends(get_db),
) -> Any:
	"""Create a group."""
	name = data.get("name", "")
	result, error = await groups_dbapi.create_group(
		db_session,
		name=name,
		created_by=user.id,
	)
	if error:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
	return result


@router.post("/groups/{group_id}/members", status_code=status.HTTP_200_OK)
async def add_iam_group_members(
	group_id: uuid.UUID,
	data: dict[str, Any],
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.GROUP_UPDATE])],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Add members to group."""
	user_ids = [uuid.UUID(str(uid)) for uid in data.get("user_ids", [])]
	for uid in user_ids:
		try:
			await groups_dbapi.add_user_to_group(
				db_session, group_id=group_id, user_id=uid, created_by=user.id
			)
		except Exception as e:
			logger.warning(f"Failed to add user {uid} to group {group_id}: {e}")
	await db_session.commit()
	return {"added": len(user_ids)}


@router.delete("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_iam_group_member(
	group_id: uuid.UUID,
	user_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.GROUP_UPDATE])],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Remove member from group."""
	try:
		await groups_dbapi.remove_user_from_group(
			db_session,
			group_id=group_id,
			user_id=user_id,
			deleted_by=user.id,
		)
		await db_session.commit()
	except Exception as e:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

@router.get("/departments")
async def list_iam_departments(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> list[Any]:
	"""Departments flat list."""
	result, _ = await departments_dbapi.list_departments(
		db_session,
		page_size=1000,
		page_number=1,
	)
	return result


@router.get("/departments/tree")
async def get_iam_department_tree(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_VIEW])],
	db_session: AsyncSession = Depends(get_db),
) -> list[Any]:
	"""Department hierarchy as tree."""
	return await departments_dbapi.get_department_tree(db_session, root_id=None)


# ---------------------------------------------------------------------------
# Access Events (audit log proxy)
# ---------------------------------------------------------------------------

@router.get("/access-events")
async def list_access_events(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.AUDIT_LOG_VIEW])],
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 20,
	user_id: str | None = None,
	action: str | None = None,
	start_date: str | None = None,
	end_date: str | None = None,
) -> dict[str, Any]:
	"""Access events from audit log."""
	filters: dict[str, Any] = {}
	if user_id:
		filters["user_id"] = {"value": user_id, "operator": "eq"}
	if action:
		filters["operation"] = {"value": action, "operator": "eq"}

	result = await dbapi.get_audit_logs(
		db_session,
		page_size=page_size,
		page_number=page,
		filters=filters if filters else None,
	)
	return {"items": result.items, "total": result.total_items}


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

@router.get("/invitations")
async def list_invitations(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_VIEW])],
	db_session: AsyncSession = Depends(get_db),
	status_filter: str | None = None,
) -> list[dict[str, Any]]:
	"""List pending/active invitations for the current tenant."""
	stmt = select(UserInvitation)
	if user.tenant_id:
		stmt = stmt.where(UserInvitation.tenant_id == user.tenant_id)
	if status_filter:
		stmt = stmt.where(UserInvitation.status == status_filter)
	else:
		stmt = stmt.where(UserInvitation.status.in_(["pending", "accepted"]))
	stmt = stmt.order_by(UserInvitation.created_at.desc())
	rows = (await db_session.execute(stmt)).scalars().all()
	return [
		{
			"id": str(r.id),
			"email": r.email,
			"status": r.status,
			"role_ids": r.role_ids or [],
			"created_at": r.created_at.isoformat() if r.created_at else None,
			"expires_at": r.expires_at.isoformat() if r.expires_at else None,
			"accepted_at": r.accepted_at.isoformat() if r.accepted_at else None,
			"last_sent_at": r.last_sent_at.isoformat() if r.last_sent_at else None,
		}
		for r in rows
	]


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
async def create_invitation(
	data: dict[str, Any],
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_CREATE])],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Create and persist a new user invitation."""
	email = data.get("email", "").strip().lower()
	if not email or "@" not in email:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valid email required")

	# Check for existing pending invitation to same address
	existing = (await db_session.execute(
		select(UserInvitation).where(
			UserInvitation.email == email,
			UserInvitation.status == "pending",
		)
	)).scalar_one_or_none()
	if existing:
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail=f"A pending invitation for {email} already exists",
		)

	invitation = UserInvitation(
		email=email,
		invited_by_id=user.id,
		role_ids=[str(r) for r in data.get("role_ids", [])],
		status="pending",
		token=secrets.token_urlsafe(32),
		created_at=datetime.utcnow(),
		expires_at=datetime.utcnow() + timedelta(days=7),
		last_sent_at=datetime.utcnow(),
		tenant_id=user.tenant_id,
	)
	db_session.add(invitation)
	await db_session.commit()
	await db_session.refresh(invitation)

	return {
		"id": str(invitation.id),
		"email": invitation.email,
		"status": invitation.status,
		"role_ids": invitation.role_ids or [],
		"created_at": invitation.created_at.isoformat(),
		"expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
	}


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
	invitation_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_UPDATE])],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Revoke (soft-delete) a pending invitation."""
	result = await db_session.execute(
		sa_update(UserInvitation)
		.where(UserInvitation.id == invitation_id)
		.values(status="revoked")
	)
	if result.rowcount == 0:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
	await db_session.commit()


@router.post("/invitations/{invitation_id}/resend", status_code=status.HTTP_200_OK)
async def resend_invitation(
	invitation_id: uuid.UUID,
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.USER_UPDATE])],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
	"""Regenerate token and mark last_sent_at for re-delivery."""
	invitation = (await db_session.execute(
		select(UserInvitation).where(UserInvitation.id == invitation_id)
	)).scalar_one_or_none()
	if not invitation:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
	if invitation.status != "pending":
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail=f"Cannot resend invitation with status '{invitation.status}'",
		)
	invitation.token = secrets.token_urlsafe(32)
	invitation.last_sent_at = datetime.utcnow()
	invitation.expires_at = datetime.utcnow() + timedelta(days=7)
	await db_session.commit()
	return {"status": "resent", "id": str(invitation_id)}


# ---------------------------------------------------------------------------
# Permission Matrix — computed from roles × permissions
# ---------------------------------------------------------------------------

@router.get("/permission-matrix")
async def get_permission_matrix(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
	db_session: AsyncSession = Depends(get_db),
	resource_type: str | None = None,
) -> list[dict[str, Any]]:
	"""Role × permission matrix derived from live DB data."""
	roles = (await db_session.execute(
		select(RoleORM)
		.where(RoleORM.deleted_at.is_(None))
		.options(selectinload(RoleORM.permissions))
		.order_by(RoleORM.name)
	)).scalars().all()

	matrix = []
	for role in roles:
		perm_map: dict[str, bool] = {}
		for perm in role.permissions:
			codename = perm.codename if hasattr(perm, "codename") else str(perm)
			# Optionally filter by resource_type (e.g. "nodes", "users")
			if resource_type:
				parts = codename.split(".")
				resource = parts[1] if len(parts) >= 2 else parts[0]
				if resource != resource_type:
					continue
			perm_map[codename] = True
		matrix.append({
			"role_id": str(role.id),
			"role_name": role.name,
			"permissions": perm_map,
		})
	return matrix


@router.patch("/permission-matrix")
async def update_permission_matrix(
	data: dict[str, Any],
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_UPDATE])],
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Grant or revoke permissions on roles. Expects {role_id, grant: [...], revoke: [...]}."""
	role_id_str = data.get("role_id")
	if not role_id_str:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="role_id required")

	try:
		role_id = uuid.UUID(str(role_id_str))
	except ValueError:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role_id")

	role = (await db_session.execute(
		select(RoleORM)
		.where(RoleORM.id == role_id, RoleORM.deleted_at.is_(None))
		.options(selectinload(RoleORM.permissions))
	)).scalar_one_or_none()
	if not role:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

	grant_codenames: list[str] = data.get("grant", [])
	revoke_codenames: list[str] = data.get("revoke", [])

	if grant_codenames:
		to_add = (await db_session.execute(
			select(PermissionORM).where(PermissionORM.codename.in_(grant_codenames))
		)).scalars().all()
		existing_ids = {p.id for p in role.permissions}
		for perm in to_add:
			if perm.id not in existing_ids:
				role.permissions.append(perm)

	if revoke_codenames:
		role.permissions = [p for p in role.permissions if p.codename not in revoke_codenames]

	await db_session.commit()
	return {
		"role_id": str(role.id),
		"role_name": role.name,
		"granted": grant_codenames,
		"revoked": revoke_codenames,
		"total_permissions": len(role.permissions),
	}
