# (c) Copyright Datacraft, 2026
"""Department schemas."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

from papermerge.core.schemas.common import ByUser


class PermissionLevel(str, Enum):
	"""Permission levels for department access rules."""
	NONE = "none"
	VIEW = "view"
	EDIT = "edit"
	DELETE = "delete"
	ADMIN = "admin"


class Department(BaseModel):
	"""Department model."""
	id: uuid.UUID
	name: str
	code: str | None = None
	description: str | None = None
	parent_id: uuid.UUID | None = None
	is_active: bool = True
	created_at: datetime | None = None
	updated_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class DepartmentCreate(BaseModel):
	"""Create department request."""
	name: str = Field(..., min_length=1, max_length=255)
	code: str | None = Field(None, max_length=50)
	description: str | None = Field(None, max_length=1000)
	parent_id: uuid.UUID | None = None

	model_config = ConfigDict(from_attributes=True)


class DepartmentUpdate(BaseModel):
	"""Update department request."""
	name: str | None = Field(None, min_length=1, max_length=255)
	code: str | None = Field(None, max_length=50)
	description: str | None = Field(None, max_length=1000)
	parent_id: uuid.UUID | None = None
	is_active: bool | None = None

	model_config = ConfigDict(from_attributes=True)


class DepartmentTree(BaseModel):
	"""Department with children for tree view."""
	id: uuid.UUID
	name: str
	code: str | None = None
	description: str | None = None
	parent_id: uuid.UUID | None = None
	is_active: bool = True
	children: list["DepartmentTree"] = Field(default_factory=list)
	member_count: int = 0
	head_user: ByUser | None = None

	model_config = ConfigDict(from_attributes=True)


class DepartmentDetails(BaseModel):
	"""Department with full details."""
	id: uuid.UUID
	name: str
	code: str | None = None
	description: str | None = None
	parent_id: uuid.UUID | None = None
	parent: Department | None = None
	is_active: bool = True
	created_at: datetime
	created_by: ByUser | None = None
	updated_at: datetime
	updated_by: ByUser | None = None
	members: list["UserDepartment"] = Field(default_factory=list)
	access_rules: list["DepartmentAccessRule"] = Field(default_factory=list)
	child_count: int = 0

	model_config = ConfigDict(from_attributes=True)


class UserDepartment(BaseModel):
	"""User's department membership."""
	user_id: uuid.UUID
	department_id: uuid.UUID
	is_head: bool = False
	is_primary: bool = False
	joined_at: datetime | None = None
	user: ByUser | None = None
	department: Department | None = None

	model_config = ConfigDict(from_attributes=True)


class UserDepartmentCreate(BaseModel):
	"""Add user to department."""
	user_id: uuid.UUID
	is_head: bool = False
	is_primary: bool = False

	model_config = ConfigDict(from_attributes=True)


class UserDepartmentUpdate(BaseModel):
	"""Update user's department membership."""
	is_head: bool | None = None
	is_primary: bool | None = None

	model_config = ConfigDict(from_attributes=True)


class DepartmentAccessRule(BaseModel):
	"""Department access rule for document types."""
	id: uuid.UUID
	department_id: uuid.UUID
	document_type_id: uuid.UUID | None = None
	permission_level: PermissionLevel = PermissionLevel.VIEW
	can_create: bool = False
	can_share: bool = False
	inherit_to_children: bool = True
	created_at: datetime | None = None
	updated_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class DepartmentAccessRuleCreate(BaseModel):
	"""Create access rule."""
	document_type_id: uuid.UUID | None = None
	permission_level: PermissionLevel = PermissionLevel.VIEW
	can_create: bool = False
	can_share: bool = False
	inherit_to_children: bool = True

	model_config = ConfigDict(from_attributes=True)


class DepartmentAccessRuleUpdate(BaseModel):
	"""Update access rule."""
	permission_level: PermissionLevel | None = None
	can_create: bool | None = None
	can_share: bool | None = None
	inherit_to_children: bool | None = None

	model_config = ConfigDict(from_attributes=True)


class DepartmentParams(BaseModel):
	"""Query parameters for department listing."""
	page_size: int = Query(25, ge=1, le=100, description="Items per page")
	page_number: int = Query(1, ge=1, description="Page number")
	sort_by: str | None = Query(
		None,
		pattern="^(id|name|code|created_at|updated_at)$",
		description="Sort column"
	)
	sort_direction: Literal["asc", "desc"] | None = Query(None, description="Sort direction")
	filter_parent_id: uuid.UUID | None = Query(None, description="Filter by parent")
	filter_is_active: bool | None = Query(None, description="Filter by active status")
	filter_free_text: str | None = Query(None, description="Search in name, code, description")

	def to_filters(self) -> dict[str, dict[str, Any]] | None:
		filters = {}

		if self.filter_parent_id is not None:
			filters["parent_id"] = {"value": self.filter_parent_id, "operator": "eq"}

		if self.filter_is_active is not None:
			filters["is_active"] = {"value": self.filter_is_active, "operator": "eq"}

		if self.filter_free_text:
			filters["free_text"] = {"value": self.filter_free_text, "operator": "free_text"}

		return filters if filters else None


# Update forward references
DepartmentTree.model_rebuild()
DepartmentDetails.model_rebuild()
