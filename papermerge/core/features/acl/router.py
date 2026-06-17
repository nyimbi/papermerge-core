"""Access Control List endpoints.

Routes
------
GET    /acl/{resource_type}/{resource_id}              — list ACL entries
POST   /acl/{resource_type}/{resource_id}              — grant access
PATCH  /acl/{resource_type}/{resource_id}/{acl_id}     — update permissions
DELETE /acl/{resource_type}/{resource_id}/{acl_id}     — revoke access
GET    /acl/{resource_type}/{resource_id}/my-perms     — current user effective perms
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Security, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import schema
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user, scopes
from papermerge.core.features.acl.db.orm import DocumentACL
from papermerge.core.features.acl.service import get_user_permissions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/acl", tags=["acl"])

ResourceType = Literal["document", "folder"]
PrincipalType = Literal["user", "group"]


# ---------------------------------------------------------------------------
# I/O schemas
# ---------------------------------------------------------------------------

class ACLEntryOut(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	resource_type: str
	resource_id: str
	principal_type: str
	principal_id: str
	principal_name: str
	can_read: bool
	can_write: bool
	can_delete: bool
	can_share: bool
	granted_by_id: str
	tenant_id: str | None
	created_at: str
	expires_at: str | None


class GrantAccessRequest(BaseModel):
	principal_type: PrincipalType
	principal_id: str
	principal_name: str
	can_read: bool = True
	can_write: bool = False
	can_delete: bool = False
	can_share: bool = False
	expires_at: datetime | None = None


class UpdateAccessRequest(BaseModel):
	can_read: bool | None = None
	can_write: bool | None = None
	can_delete: bool | None = None
	can_share: bool | None = None
	expires_at: datetime | None = None
	principal_name: str | None = None


class EffectivePermsOut(BaseModel):
	can_read: bool
	can_write: bool
	can_delete: bool
	can_share: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(entry: DocumentACL) -> ACLEntryOut:
	return ACLEntryOut(
		id=str(entry.id),
		resource_type=entry.resource_type,
		resource_id=entry.resource_id,
		principal_type=entry.principal_type,
		principal_id=entry.principal_id,
		principal_name=entry.principal_name,
		can_read=entry.can_read,
		can_write=entry.can_write,
		can_delete=entry.can_delete,
		can_share=entry.can_share,
		granted_by_id=entry.granted_by_id,
		tenant_id=entry.tenant_id,
		created_at=entry.created_at.isoformat(),
		expires_at=entry.expires_at.isoformat() if entry.expires_at else None,
	)


async def _require_acl_entry(
	acl_id: uuid.UUID,
	resource_type: str,
	resource_id: str,
	session: AsyncSession,
) -> DocumentACL:
	entry = (
		await session.execute(
			select(DocumentACL).where(
				DocumentACL.id == acl_id,
				DocumentACL.resource_type == resource_type,
				DocumentACL.resource_id == resource_id,
			)
		)
	).scalar_one_or_none()
	if not entry:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="ACL entry not found",
		)
	return entry


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
	"/{resource_type}/{resource_id}",
	response_model=list[ACLEntryOut],
)
async def list_acl(
	resource_type: ResourceType,
	resource_id: str,
	user: Annotated[
		schema.User,
		Security(get_current_user, scopes=[scopes.SHARED_NODE_VIEW]),
	],
	db_session: AsyncSession = Depends(get_db),
) -> list[ACLEntryOut]:
	"""List all ACL entries for a document or folder."""
	rows = (
		await db_session.execute(
			select(DocumentACL)
			.where(
				DocumentACL.resource_type == resource_type,
				DocumentACL.resource_id == resource_id,
			)
			.order_by(DocumentACL.created_at.asc())
		)
	).scalars().all()
	return [_serialize(r) for r in rows]


@router.post(
	"/{resource_type}/{resource_id}",
	status_code=status.HTTP_201_CREATED,
	response_model=ACLEntryOut,
)
async def grant_access(
	resource_type: ResourceType,
	resource_id: str,
	body: GrantAccessRequest,
	user: Annotated[
		schema.User,
		Security(get_current_user, scopes=[scopes.SHARED_NODE_CREATE]),
	],
	db_session: AsyncSession = Depends(get_db),
) -> ACLEntryOut:
	"""Grant a user or group access to a document or folder."""
	# Check for duplicate
	existing = (
		await db_session.execute(
			select(DocumentACL).where(
				DocumentACL.resource_type == resource_type,
				DocumentACL.resource_id == resource_id,
				DocumentACL.principal_type == body.principal_type,
				DocumentACL.principal_id == body.principal_id,
			)
		)
	).scalar_one_or_none()

	if existing:
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail="ACL entry already exists for this principal. Use PATCH to update.",
		)

	tenant_id = getattr(user, "tenant_id", None)

	entry = DocumentACL(
		id=uuid.uuid4(),
		resource_type=resource_type,
		resource_id=resource_id,
		principal_type=body.principal_type,
		principal_id=body.principal_id,
		principal_name=body.principal_name,
		can_read=body.can_read,
		can_write=body.can_write,
		can_delete=body.can_delete,
		can_share=body.can_share,
		granted_by_id=str(user.id),
		tenant_id=str(tenant_id) if tenant_id else None,
		expires_at=body.expires_at,
	)
	db_session.add(entry)
	await db_session.commit()
	await db_session.refresh(entry)

	logger.info(
		"acl.granted resource=%s/%s principal=%s/%s by user=%s",
		resource_type, resource_id,
		body.principal_type, body.principal_id,
		user.id,
	)
	return _serialize(entry)


@router.patch(
	"/{resource_type}/{resource_id}/{acl_id}",
	response_model=ACLEntryOut,
)
async def update_access(
	resource_type: ResourceType,
	resource_id: str,
	acl_id: uuid.UUID,
	body: UpdateAccessRequest,
	user: Annotated[
		schema.User,
		Security(get_current_user, scopes=[scopes.SHARED_NODE_UPDATE]),
	],
	db_session: AsyncSession = Depends(get_db),
) -> ACLEntryOut:
	"""Update permission flags on an existing ACL entry."""
	entry = await _require_acl_entry(acl_id, resource_type, resource_id, db_session)

	if body.can_read is not None:
		entry.can_read = body.can_read
	if body.can_write is not None:
		entry.can_write = body.can_write
	if body.can_delete is not None:
		entry.can_delete = body.can_delete
	if body.can_share is not None:
		entry.can_share = body.can_share
	if body.expires_at is not None:
		entry.expires_at = body.expires_at
	if body.principal_name is not None:
		entry.principal_name = body.principal_name

	await db_session.commit()
	await db_session.refresh(entry)

	logger.info(
		"acl.updated acl_id=%s resource=%s/%s by user=%s",
		acl_id, resource_type, resource_id, user.id,
	)
	return _serialize(entry)


@router.delete(
	"/{resource_type}/{resource_id}/{acl_id}",
	status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_access(
	resource_type: ResourceType,
	resource_id: str,
	acl_id: uuid.UUID,
	user: Annotated[
		schema.User,
		Security(get_current_user, scopes=[scopes.SHARED_NODE_DELETE]),
	],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Revoke an ACL entry (hard delete)."""
	entry = await _require_acl_entry(acl_id, resource_type, resource_id, db_session)
	await db_session.delete(entry)
	await db_session.commit()

	logger.info(
		"acl.revoked acl_id=%s resource=%s/%s by user=%s",
		acl_id, resource_type, resource_id, user.id,
	)


@router.get(
	"/{resource_type}/{resource_id}/my-perms",
	response_model=EffectivePermsOut,
)
async def my_permissions(
	resource_type: ResourceType,
	resource_id: str,
	user: Annotated[
		schema.User,
		Security(get_current_user, scopes=[scopes.NODE_VIEW]),
	],
	db_session: AsyncSession = Depends(get_db),
) -> EffectivePermsOut:
	"""Return the effective permissions of the calling user on this resource."""
	group_ids: list[str] = [
		str(g) for g in getattr(user, "group_ids", []) or []
	]
	perms = await get_user_permissions(
		user_id=str(user.id),
		resource_id=resource_id,
		resource_type=resource_type,
		group_ids=group_ids,
		session=db_session,
	)
	return EffectivePermsOut(**perms)
