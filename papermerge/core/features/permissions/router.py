# (c) Copyright Datacraft, 2026
"""Permissions router for role management."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Security
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import schema
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user, scopes
from papermerge.core.features.roles.db.orm import Permission as PermissionORM

router = APIRouter(prefix="/permissions", tags=["permissions"])
logger = logging.getLogger(__name__)


class Permission(BaseModel):
	id: str
	codename: str
	name: str
	category: str
	description: str | None = None


class PermissionCategory(BaseModel):
	name: str
	permissions: list[Permission]


SCOPE_CATEGORIES = {
	"document": "documents", "node": "documents", "page": "documents",
	"folder": "folders", "tag": "tags", "user": "users",
	"group": "groups", "role": "roles", "workflow": "workflows",
	"scan": "scanning", "batch": "scanning", "setting": "settings",
	"billing": "billing", "custom_field": "settings", "document_type": "settings",
}


def _orm_to_perm(p: PermissionORM) -> Permission:
	category = "settings"
	for key, cat in SCOPE_CATEGORIES.items():
		if key in p.codename.lower():
			category = cat
			break
	return Permission(
		id=str(p.id),
		codename=p.codename,
		name=p.name or p.codename.replace(".", " ").replace("_", " ").title(),
		category=category,
		description=f"Permission for {p.codename}",
	)


@router.get("")
async def get_permissions(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
	db: AsyncSession = Depends(get_db),
) -> list[Permission]:
	"""Get all permissions from DB (stable IDs)."""
	rows = (await db.execute(select(PermissionORM).order_by(PermissionORM.codename))).scalars().all()
	return [_orm_to_perm(p) for p in rows]


@router.get("/by-category")
async def get_permissions_by_category(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
	db: AsyncSession = Depends(get_db),
) -> list[PermissionCategory]:
	"""Get permissions grouped by category."""
	rows = (await db.execute(select(PermissionORM).order_by(PermissionORM.codename))).scalars().all()
	perms = [_orm_to_perm(p) for p in rows]
	categories: dict[str, list[Permission]] = {}
	for p in perms:
		categories.setdefault(p.category, []).append(p)
	return [PermissionCategory(name=name, permissions=ps) for name, ps in sorted(categories.items())]


@router.get("/resource-types")
async def get_resource_types(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
) -> list[str]:
	"""Get all resource types used in policies."""
	return [
		"document", "folder", "tag", "workflow", "batch",
		"scanner", "user", "group", "role", "report",
		"invoice", "case", "portfolio", "template",
	]
