# (c) Copyright Datacraft, 2026
"""Permissions router for role management."""
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Security
from pydantic import BaseModel

from papermerge.core import schema
from papermerge.core.features.auth import get_current_user, scopes

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


# Map scopes to categories
SCOPE_CATEGORIES = {
	"document": "documents", "node": "documents", "page": "documents",
	"folder": "folders", "tag": "tags", "user": "users",
	"group": "groups", "role": "roles", "workflow": "workflows",
	"scan": "scanning", "batch": "scanning", "setting": "settings",
	"billing": "billing", "custom_field": "settings", "document_type": "settings",
}


def scope_to_permission(scope: str) -> Permission:
	parts = scope.split(".")
	category = "settings"
	for key, cat in SCOPE_CATEGORIES.items():
		if key in scope.lower():
			category = cat
			break
	return Permission(
		id=str(uuid4()),
		codename=scope,
		name=scope.replace(".", " ").replace("_", " ").title(),
		category=category,
		description=f"Permission for {scope}",
	)


@router.get("")
async def get_permissions(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
) -> list[Permission]:
	"""Get all permissions."""
	all_scopes = scopes.Scopes().all_scopes()
	return [scope_to_permission(s) for s in sorted(all_scopes)]


@router.get("/by-category")
async def get_permissions_by_category(
	user: Annotated[schema.User, Security(get_current_user, scopes=[scopes.ROLE_VIEW])],
) -> list[PermissionCategory]:
	"""Get permissions grouped by category."""
	all_scopes = scopes.Scopes().all_scopes()
	perms = [scope_to_permission(s) for s in sorted(all_scopes)]

	categories: dict[str, list[Permission]] = {}
	for p in perms:
		categories.setdefault(p.category, []).append(p)

	return [PermissionCategory(name=name, permissions=ps) for name, ps in sorted(categories.items())]
