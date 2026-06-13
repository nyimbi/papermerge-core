import os
import logging
from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from papermerge.core.features.auth import get_current_user, scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core import schema, dbapi, orm
from papermerge.core.tasks import delete_user_data
from papermerge.core.routers.common import OPEN_API_GENERIC_JSON_DETAIL
from papermerge.core.db.engine import get_db
from papermerge.core.features.audit.db.audit_context import AsyncAuditContext
from .schema import UserParams

router = APIRouter(
    prefix="/users",
    tags=["users"],
)

logger = logging.getLogger(__name__)


@router.get("/group-homes")
async def get_user_group_homes(
    user: require_scopes(scopes.NODE_VIEW),
    db_session: AsyncSession=Depends(get_db),
) -> list[schema.UserHome]:
    """Get all user group homes"""
    result, error = await dbapi.get_user_group_homes(db_session, user_id=user.id)

    if error:
        raise HTTPException(status_code=400, detail=error)

    return result


@router.get("/group-inboxes")
async def get_user_group_inboxes(
    user: require_scopes(scopes.NODE_VIEW),
    db_session: AsyncSession = Depends(get_db),
) -> list[schema.UserInbox]:
    """Get all user group inboxes"""
    result, error = await dbapi.get_user_group_inboxes(db_session, user_id=user.id)

    if error:
        raise HTTPException(status_code=400, detail=error)

    return result


@router.get("/me")
async def get_current_user_info(
    user: Annotated[schema.User, Depends(get_current_user)],
) -> schema.User:
    """Returns current user"""
    return user


@router.patch("/me")
async def update_current_user(
    updates: dict,
    user: Annotated[schema.User, Depends(get_current_user)],
    db_session: AsyncSession = Depends(get_db),
) -> schema.User:
    """Update current user's own profile (email, username)."""
    from papermerge.core.features.users.db.orm import User as UserORM
    db_user = await db_session.get(UserORM, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if "email" in updates and updates["email"]:
        db_user.email = updates["email"]
    if "username" in updates and updates["username"]:
        db_user.username = updates["username"]
    try:
        await db_session.commit()
        await db_session.refresh(db_user)
    except IntegrityError:
        await db_session.rollback()
        raise HTTPException(status_code=400, detail="Username or email already taken")
    return schema.User.model_validate(db_user)


@router.get("/group-users")
async def get_user_group_users(
    user: Annotated[schema.User, Depends(get_current_user)],
    db_session: AsyncSession = Depends(get_db),
) -> list[schema.UserSimple]:
    """Get all users from groups that current user belongs to

    No special scope required - any authenticated user can see
    users they share group membership with.

    Returns:
        List of users (excluding current user) who are members of
        the same groups as the current user

    Raises:
        HTTPException: 500 if database error occurs
    """
    try:
        result = await dbapi.get_user_group_users(
            db_session,
            user_id=user.id
        )
        return result
    except Exception as e:
        logger.error(
            f"Error fetching group users for user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch group users"
        )


@router.get("/user-groups")
async def get_user_groups_for_current_user(
    user: Annotated[schema.User, Depends(get_current_user)],
    db_session: AsyncSession = Depends(get_db),
) -> list[schema.GroupShort]:
    """Get all groups to which current user belongs

    No special scope required - any authenticated user can see
    groups they are member of

    Returns:
        List of groups which current user is part of

    Raises:
        HTTPException: 500 if database error occurs
    """
    try:
        groups = await dbapi.get_user_groups(
            db_session,
            user_id=user.id
        )
    except Exception as e:
        logger.error(
            f"Error fetching groups user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch groups for user"
        )

    return groups


@router.get("/")
async def get_users(
    user: require_scopes(scopes.USER_VIEW),
    params: UserParams = Depends(),
    db_session: AsyncSession=Depends(get_db),
) -> schema.PaginatedResponse[schema.UserEx]:
    """Get all users"""

    try:
        filters = params.to_filters()
        paginated_users = await dbapi.get_users(
            db_session,
            page_size=params.page_size,
            page_number=params.page_number,
            sort_by=params.sort_by,
            sort_direction=params.sort_direction,
            filters=filters
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {str(e)}")
    except Exception as e:
        logger.error(
            f"Error fetching users by the user {user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")


    return paginated_users


@router.get("/all", response_model=list[schema.User])
async def get_users_without_pagination(
    user: require_scopes(scopes.USER_SELECT),
    db_session: AsyncSession=Depends(get_db),
):
    """Get all users without pagination/filtering/sorting"""
    result = await dbapi.get_users_without_pagination(db_session)

    return result


@router.post(
    "/",
    status_code=201,
    responses={
        400: {"description": "Invalid parameters or validation error"},
        404: {"description": "Specified roles or groups not found"},
        409: {"description": "User with username or email already exists"},
        500: {"description": "Internal server error"}
    }
)
async def create_user(
    pyuser: schema.CreateUser,
    cur_user: require_scopes(scopes.USER_CREATE),
    db_session: AsyncSession = Depends(get_db),
) -> schema.User:
    """Creates user"""

    if pyuser.role_ids:
        # Validate roles exist and are active
        roles_result = await db_session.execute(
            select(orm.Role.id).where(
                orm.Role.id.in_(pyuser.role_ids),
                orm.Role.deleted_at.is_(None)
            )
        )
        found_role_ids = set(roles_result.scalars().all())
        missing_roles = set(pyuser.role_ids) - found_role_ids
        if missing_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid or inactive role IDs: {missing_roles}"
            )
    try:
        async with AsyncAuditContext(
            db_session,
            user_id=cur_user.id,
            username=cur_user.username
        ):
            db_user = await dbapi.create_user(
                db_session,
                username=pyuser.username,
                email=pyuser.email,
                password=pyuser.password,
                role_ids=pyuser.role_ids,
                is_active=pyuser.is_active,
                is_superuser=pyuser.is_superuser,
                group_ids=pyuser.group_ids,
            )
    except IntegrityError as e:
        await db_session.rollback()
        error_msg = str(e).lower()
        if "username" in error_msg:
            raise HTTPException(
                status_code=409,
                detail="A user with this username already exists"
            )
        elif "email" in error_msg:
            raise HTTPException(
                status_code=409,
                detail="A user with this email already exists"
            )
        else:
            logger.error(f"IntegrityError creating user by {cur_user.username}: {e}", exc_info=True)
            raise HTTPException(status_code=409, detail="User already exists")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {str(e)}")
    except Exception as e:
        logger.error(
            f"Error creating user {cur_user.id}: {e}",
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return db_user


@router.get(
    "/{user_id}",
    status_code=200,
    responses={
        404: {
            "description": """No user with specified UUID found""",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        }
    },
    response_model=schema.UserDetails,
)
async def get_user_details(
    user_id: UUID,
    user: require_scopes(scopes.USER_VIEW),
    db_session: AsyncSession  =Depends(get_db),
):
    """Get user details"""
    user, error = await dbapi.get_user_details(
        db_session,
        user_id=user_id,
    )

    if error:
        raise HTTPException(status_code=404, detail=error.model_dump())

    return user


@router.delete(
    "/{user_id}",
    status_code=204,
    responses={
        432: {
            "description": """Deletion is not possible because there is only
             one user left""",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
        404: {
            "description": """No user with specified UUID found""",
            "content": OPEN_API_GENERIC_JSON_DETAIL,
        },
    },
)
async def delete_user(
    user_id: UUID,
    cur_user: require_scopes(scopes.USER_DELETE),
    db_session: AsyncSession=Depends(get_db),
) -> None:
    """Deletes user"""

    if await dbapi.get_users_count(db_session) == 1:
        raise HTTPException(
            status_code=432, detail="Deletion not possible. Only one user left."
        )

    try:
        if os.environ.get("PAPERMERGE__REDIS__URL"):
            delete_user_data.apply_async(kwargs={"user_id": str(user_id)})
        else:
            async with AsyncAuditContext(
                db_session,
                user_id=cur_user.id,
                username=cur_user.username
            ):
                await dbapi.delete_user(
                    db_session,
                    user_id=user_id,
                    deleted_by_user_id=cur_user.id
                )
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=469, detail=str(e))


@router.patch("/{user_id}", status_code=200, response_model=schema.UserDetails)
async def update_user(
    user_id: UUID,
    attrs: schema.UpdateUser,
    cur_user: require_scopes(scopes.USER_UPDATE),
    db_session: AsyncSession=Depends(get_db),
) -> schema.UserDetails:
    """Updates user"""

    async with AsyncAuditContext(
        db_session,
        user_id=cur_user.id,
        username=cur_user.username
    ):
        user, error = await dbapi.update_user(db_session, user_id=user_id, attrs=attrs)

    if error:
        raise HTTPException(status_code=404, detail=error.model_dump())

    return user


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    response_model=schema.UserDetails
)
async def change_user_password(
    attrs: schema.ChangeUserPassword,
    cur_user: require_scopes(scopes.USER_UPDATE),
    db_session: AsyncSession = Depends(get_db),
) -> schema.UserDetails:
    """Change user password"""
    async with AsyncAuditContext(
        db_session,
        user_id=cur_user.id,
        username=cur_user.username
    ):
        user, error = await dbapi.change_password(
            db_session,
            user_id=UUID(attrs.userId),
            password=attrs.password
        )

    if error:
        if "not found" in str(error.messages).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error.model_dump()
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error.model_dump()
            )

    return user


@router.patch("/{user_id}/roles", status_code=200)
async def update_user_roles(
	user_id: UUID,
	data: dict,
	cur_user: require_scopes(scopes.USER_UPDATE),
	db_session: AsyncSession = Depends(get_db),
):
	"""Update roles for a user."""
	role_ids = data.get("role_ids", [])
	from papermerge.core.features.roles.db.orm import Role as RoleModel
	from papermerge.core.features.users.db.orm import User as UserORM
	from sqlalchemy import select as sa_select
	result = await db_session.execute(sa_select(UserORM).where(UserORM.id == user_id))
	user = result.scalar_one_or_none()
	if not user:
		raise HTTPException(status_code=404, detail="User not found")
	roles_result = await db_session.execute(
		sa_select(RoleModel).where(RoleModel.id.in_([str(r) for r in role_ids]))
	)
	user.roles = list(roles_result.scalars().all())
	await db_session.commit()
	return {"user_id": str(user_id), "role_ids": role_ids}


@router.post("/bulk-roles", status_code=200)
async def bulk_update_user_roles(
	data: dict,
	cur_user: require_scopes(scopes.USER_UPDATE),
	db_session: AsyncSession = Depends(get_db),
):
	"""Bulk update roles for multiple users."""
	from uuid import UUID as _UUID
	from sqlalchemy import delete as sa_delete
	from papermerge.core.features.roles.db.orm import UserRole

	user_ids = [_UUID(str(uid)) for uid in data.get("user_ids", [])]
	add_role_ids = [_UUID(str(rid)) for rid in data.get("add_role_ids", [])]
	remove_role_ids = [_UUID(str(rid)) for rid in data.get("remove_role_ids", [])]

	added = removed = 0

	for user_id in user_ids:
		# Add roles — skip existing to avoid unique constraint violations
		if add_role_ids:
			existing_stmt = select(UserRole.role_id).where(
				UserRole.user_id == user_id,
				UserRole.role_id.in_(add_role_ids),
			)
			existing = set((await db_session.execute(existing_stmt)).scalars().all())
			for role_id in add_role_ids:
				if role_id not in existing:
					db_session.add(UserRole(user_id=user_id, role_id=role_id))
					added += 1

		# Remove roles
		if remove_role_ids:
			del_result = await db_session.execute(
				sa_delete(UserRole).where(
					UserRole.user_id == user_id,
					UserRole.role_id.in_(remove_role_ids),
				)
			)
			removed += del_result.rowcount

	await db_session.commit()
	return {
		"updated": len(user_ids),
		"roles_added": added,
		"roles_removed": removed,
	}


@router.post("/bulk-status", status_code=200)
async def bulk_update_user_status(
	data: dict,
	cur_user: require_scopes(scopes.USER_UPDATE),
	db_session: AsyncSession = Depends(get_db),
):
	"""Bulk update status for multiple users."""
	user_ids = data.get("user_ids", [])
	new_status = data.get("status", "active")
	from papermerge.core.features.users.db.orm import User as UserORM
	from sqlalchemy import update as sa_update
	is_active = new_status == "active"
	await db_session.execute(
		sa_update(UserORM)
		.where(UserORM.id.in_([str(uid) for uid in user_ids]))
		.values(is_active=is_active)
	)
	await db_session.commit()
	return {"updated": len(user_ids), "status": new_status}


@router.get("/export")
async def export_users(
	cur_user: require_scopes(scopes.USER_VIEW),
	db_session: AsyncSession = Depends(get_db),
	user_ids: list[str] | None = None,
):
	"""Export users as JSON."""
	import json
	from fastapi.responses import Response
	from papermerge.core.features.users.db.orm import User as UserORM
	from sqlalchemy import select as sa_select
	stmt = sa_select(UserORM)
	if user_ids:
		stmt = stmt.where(UserORM.id.in_(user_ids))
	result = await db_session.execute(stmt)
	users = result.scalars().all()
	data = [{"id": str(u.id), "username": u.username, "email": u.email, "is_active": u.is_active} for u in users]
	return Response(
		content=json.dumps(data),
		media_type="application/json",
		headers={"Content-Disposition": "attachment; filename=users.json"},
	)


@router.post("/{user_id}/mfa/enable")
async def admin_enable_mfa(
	user_id: UUID,
	cur_user: require_scopes(scopes.USER_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Admin: generate new TOTP secret for a user and return QR code."""
	import io, base64, pyotp, qrcode as _qrcode
	from papermerge.core.features.users.db.orm import User as UserORM
	from papermerge.core.features.mfa.db.orm import UserMFASettings
	from sqlalchemy import select as _sel

	target = (await db_session.execute(_sel(UserORM).where(UserORM.id == user_id))).scalar_one_or_none()
	if not target:
		raise HTTPException(status_code=404, detail="User not found")

	secret = pyotp.random_base32()
	mfa = (await db_session.execute(_sel(UserMFASettings).where(UserMFASettings.user_id == user_id))).scalar_one_or_none()
	if mfa is None:
		from datetime import datetime as _dt
		mfa = UserMFASettings(user_id=user_id, created_at=_dt.utcnow(), updated_at=_dt.utcnow())
		db_session.add(mfa)
	mfa.totp_secret = secret
	mfa.totp_enabled = False
	await db_session.commit()

	label = target.email or target.username
	uri = pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name="dArchiva")
	img = _qrcode.make(uri)
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	qr_b64 = base64.b64encode(buf.getvalue()).decode()
	return {"qr_code": f"data:image/png;base64,{qr_b64}", "secret": secret}


@router.post("/{user_id}/mfa/disable", status_code=200)
async def admin_disable_mfa(
	user_id: UUID,
	cur_user: require_scopes(scopes.USER_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Admin: disable MFA for a user."""
	from papermerge.core.features.mfa.db.orm import UserMFASettings
	from sqlalchemy import select as _sel

	mfa = (await db_session.execute(_sel(UserMFASettings).where(UserMFASettings.user_id == user_id))).scalar_one_or_none()
	if mfa:
		mfa.totp_enabled = False
		mfa.totp_secret = None
		mfa.backup_codes = None
		await db_session.commit()
	return {"disabled": True}


@router.post("/{user_id}/reset-password", status_code=200)
async def admin_reset_password(
	user_id: UUID,
	body: dict,
	cur_user: require_scopes(scopes.USER_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Admin: set a new password for a user."""
	from passlib.hash import pbkdf2_sha256
	from papermerge.core.features.users.db.orm import User as UserORM

	new_password = body.get("password") or body.get("new_password")
	if not new_password or len(new_password) < 8:
		raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

	target = await db_session.get(UserORM, user_id)
	if not target:
		raise HTTPException(status_code=404, detail="User not found")

	target.password = pbkdf2_sha256.hash(new_password)
	await db_session.commit()
	return {"reset": True}
