import logging
import secrets
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import dbapi, schema
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.groups.db.api import get_groups
from papermerge.core.features.groups.schema import GroupParams
from .schema import UserParams

router = APIRouter(
	prefix="/admin",
	tags=["admin"],
)

logger = logging.getLogger(__name__)


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def admin_list_users(
	cur_user: require_scopes(scopes.USER_VIEW),
	params: UserParams = Depends(),
	db_session: AsyncSession = Depends(get_db),
) -> schema.PaginatedResponse[schema.UserEx]:
	"""List all users in the tenant (paginated).

	Returns id, username, email, is_active, is_superuser, created_at, groups.
	"""
	try:
		filters = params.to_filters()
		result = await dbapi.get_users(
			db_session,
			page_size=params.page_size,
			page_number=params.page_number,
			sort_by=params.sort_by,
			sort_direction=params.sort_direction,
			filters=filters,
		)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=f"Invalid parameters: {exc}")
	except Exception as exc:
		logger.error("admin_list_users error: %s", exc, exc_info=True)
		raise HTTPException(status_code=500, detail="Internal server error")

	return result


@router.patch("/users/{user_id}", status_code=200, response_model=schema.UserDetails)
async def admin_update_user(
	user_id: UUID,
	attrs: schema.UpdateUser,
	cur_user: require_scopes(scopes.USER_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.UserDetails:
	"""Update a user: is_active, groups, roles."""
	user, error = await dbapi.update_user(db_session, user_id=user_id, attrs=attrs)
	if error:
		raise HTTPException(status_code=404, detail=error.model_dump())
	return user


@router.post("/users/invite", status_code=201)
async def admin_invite_user(
	data: dict[str, Any],
	cur_user: require_scopes(scopes.USER_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
	"""Invite a user to the tenant by email.

	Accepted body: {email, role: "viewer"|"editor"|"admin"|"operator"}
	If a full invite system exists the invitation record is persisted;
	otherwise a pending-invite record is created.
	"""
	email = (data.get("email") or "").strip().lower()
	if not email or "@" not in email:
		raise HTTPException(status_code=400, detail="Valid email required")

	role_name: str | None = data.get("role")
	role_ids: list[str] = []

	# Resolve named role to IDs when provided
	if role_name:
		from papermerge.core.features.roles.db.orm import Role as RoleORM
		role_row = (await db_session.execute(
			select(RoleORM).where(
				RoleORM.name.ilike(role_name),
				RoleORM.deleted_at.is_(None),
			)
		)).scalar_one_or_none()
		if role_row:
			role_ids = [str(role_row.id)]

	# Try the IAM invitation table first
	try:
		from papermerge.core.features.iam.db.orm import UserInvitation
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
			invited_by_id=cur_user.id,
			role_ids=role_ids,
			status="pending",
			token=secrets.token_urlsafe(32),
			created_at=datetime.utcnow(),
			expires_at=datetime.utcnow() + timedelta(days=7),
			last_sent_at=datetime.utcnow(),
			tenant_id=cur_user.tenant_id,
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

	except HTTPException:
		raise
	except ImportError:
		# IAM invitation model not available — fall back to creating user directly
		pass
	except Exception as exc:
		logger.error("admin_invite_user invitation error: %s", exc, exc_info=True)
		# Fall through to direct creation fallback

	# Fallback: create user with temporary password
	import string, random
	temp_password = "".join(random.choices(string.ascii_letters + string.digits, k=16))
	try:
		db_user = await dbapi.create_user(
			db_session,
			username=email.split("@")[0],
			email=email,
			password=temp_password,
			role_ids=[UUID(r) for r in role_ids],
			is_active=False,
			is_superuser=False,
			group_ids=[],
		)
		return {
			"id": str(db_user.id),
			"email": db_user.email,
			"status": "created",
			"role_ids": role_ids,
			"temporary_password": temp_password,
			"created_at": db_user.created_at.isoformat(),
			"expires_at": None,
		}
	except Exception as exc:
		logger.error("admin_invite_user fallback create error: %s", exc, exc_info=True)
		raise HTTPException(status_code=500, detail="Failed to create invitation")


# ── Groups ────────────────────────────────────────────────────────────────────

@router.get("/groups")
async def admin_list_groups(
	cur_user: require_scopes(scopes.GROUP_VIEW),
	params: GroupParams = Depends(),
	db_session: AsyncSession = Depends(get_db),
) -> schema.PaginatedResponse[schema.GroupEx]:
	"""List all roles/groups."""
	try:
		filters = params.to_filters()
		result = await get_groups(
			db_session,
			page_size=params.page_size,
			page_number=params.page_number,
			sort_by=params.sort_by,
			sort_direction=params.sort_direction,
			filters=filters,
		)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=f"Invalid parameters: {exc}")
	except Exception as exc:
		logger.error("admin_list_groups error: %s", exc, exc_info=True)
		raise HTTPException(status_code=500, detail="Internal server error")

	return result


@router.patch("/groups/{group_id}", status_code=200, response_model=schema.Group)
async def admin_update_group(
	group_id: UUID,
	attrs: schema.UpdateGroup,
	cur_user: require_scopes(scopes.GROUP_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.Group:
	"""Update a group's name or special-folder configuration."""
	from sqlalchemy.exc import NoResultFound
	from papermerge.core.features.groups.db.api import update_group

	try:
		group = await update_group(db_session, group_id=group_id, attrs=attrs)
	except NoResultFound:
		raise HTTPException(status_code=404, detail="Group not found")

	return group
