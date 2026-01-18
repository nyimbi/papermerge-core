# (c) Copyright Datacraft, 2026
"""Departments API router."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_async_session
from papermerge.core.features.auth.dependencies import get_current_user_id

from .db import api as db_api
from .schema import (
	Department,
	DepartmentAccessRule,
	DepartmentAccessRuleCreate,
	DepartmentAccessRuleUpdate,
	DepartmentCreate,
	DepartmentDetails,
	DepartmentParams,
	DepartmentTree,
	DepartmentUpdate,
	UserDepartment,
	UserDepartmentCreate,
	UserDepartmentUpdate,
)

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.get("", response_model=dict)
async def list_departments(
	params: Annotated[DepartmentParams, Depends()],
	session: Annotated[AsyncSession, Depends(get_async_session)],
):
	"""List all departments with pagination."""
	departments, total = await db_api.list_departments(
		session,
		page_size=params.page_size,
		page_number=params.page_number,
		sort_by=params.sort_by,
		sort_direction=params.sort_direction,
		filters=params.to_filters(),
	)

	return {
		"items": [Department.model_validate(d) for d in departments],
		"total": total,
		"page_size": params.page_size,
		"page_number": params.page_number,
	}


@router.get("/tree", response_model=list[DepartmentTree])
async def get_department_tree(
	session: Annotated[AsyncSession, Depends(get_async_session)],
	root_id: uuid.UUID | None = None,
):
	"""Get department hierarchy as tree."""
	departments = await db_api.get_department_tree(session, root_id)

	def build_tree(dept) -> DepartmentTree:
		return DepartmentTree(
			id=dept.id,
			name=dept.name,
			code=dept.code,
			description=dept.description,
			parent_id=dept.parent_id,
			is_active=dept.is_active,
			member_count=dept.member_count,
			children=[build_tree(c) for c in dept.children if c.deleted_at is None],
			head_user=None,  # TODO: Add head user
		)

	return [build_tree(d) for d in departments]


@router.post("", response_model=Department, status_code=status.HTTP_201_CREATED)
async def create_department(
	data: DepartmentCreate,
	session: Annotated[AsyncSession, Depends(get_async_session)],
	current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
	"""Create a new department."""
	# Check for duplicate code
	if data.code:
		existing = await db_api.get_department_by_code(session, data.code)
		if existing:
			raise HTTPException(
				status_code=status.HTTP_409_CONFLICT,
				detail=f"Department with code '{data.code}' already exists",
			)

	# Validate parent exists
	if data.parent_id:
		parent = await db_api.get_department(session, data.parent_id)
		if not parent:
			raise HTTPException(
				status_code=status.HTTP_404_NOT_FOUND,
				detail="Parent department not found",
			)

	department = await db_api.create_department(
		session,
		name=data.name,
		code=data.code,
		description=data.description,
		parent_id=data.parent_id,
		created_by=current_user_id,
	)
	await session.commit()

	return Department.model_validate(department)


@router.get("/{department_id}", response_model=DepartmentDetails)
async def get_department(
	department_id: uuid.UUID,
	session: Annotated[AsyncSession, Depends(get_async_session)],
):
	"""Get department details."""
	department = await db_api.get_department(session, department_id)
	if not department:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Department not found",
		)

	return DepartmentDetails.model_validate(department)


@router.patch("/{department_id}", response_model=Department)
async def update_department(
	department_id: uuid.UUID,
	data: DepartmentUpdate,
	session: Annotated[AsyncSession, Depends(get_async_session)],
	current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
	"""Update a department."""
	# Check for duplicate code
	if data.code:
		existing = await db_api.get_department_by_code(session, data.code)
		if existing and existing.id != department_id:
			raise HTTPException(
				status_code=status.HTTP_409_CONFLICT,
				detail=f"Department with code '{data.code}' already exists",
			)

	# Prevent circular parent reference
	if data.parent_id:
		if data.parent_id == department_id:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail="Department cannot be its own parent",
			)

		parent = await db_api.get_department(session, data.parent_id)
		if not parent:
			raise HTTPException(
				status_code=status.HTTP_404_NOT_FOUND,
				detail="Parent department not found",
			)

	updates = data.model_dump(exclude_unset=True)
	department = await db_api.update_department(
		session,
		department_id,
		updated_by=current_user_id,
		**updates,
	)

	if not department:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Department not found",
		)

	await session.commit()
	return Department.model_validate(department)


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
	department_id: uuid.UUID,
	session: Annotated[AsyncSession, Depends(get_async_session)],
	current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
	"""Delete a department."""
	success = await db_api.delete_department(
		session,
		department_id,
		deleted_by=current_user_id,
	)

	if not success:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Department not found",
		)

	await session.commit()


# User memberships
@router.get("/{department_id}/members", response_model=list[UserDepartment])
async def list_department_members(
	department_id: uuid.UUID,
	session: Annotated[AsyncSession, Depends(get_async_session)],
):
	"""List department members."""
	department = await db_api.get_department(session, department_id)
	if not department:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Department not found",
		)

	return [UserDepartment.model_validate(m) for m in department.members]


@router.post(
	"/{department_id}/members",
	response_model=UserDepartment,
	status_code=status.HTTP_201_CREATED,
)
async def add_department_member(
	department_id: uuid.UUID,
	data: UserDepartmentCreate,
	session: Annotated[AsyncSession, Depends(get_async_session)],
	current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
	"""Add a user to a department."""
	department = await db_api.get_department(session, department_id)
	if not department:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Department not found",
		)

	user_dept = await db_api.add_user_to_department(
		session,
		department_id=department_id,
		user_id=data.user_id,
		is_head=data.is_head,
		is_primary=data.is_primary,
		created_by=current_user_id,
	)
	await session.commit()

	return UserDepartment.model_validate(user_dept)


@router.patch("/{department_id}/members/{user_id}", response_model=UserDepartment)
async def update_department_member(
	department_id: uuid.UUID,
	user_id: uuid.UUID,
	data: UserDepartmentUpdate,
	session: Annotated[AsyncSession, Depends(get_async_session)],
	current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
	"""Update a user's department membership."""
	updates = data.model_dump(exclude_unset=True)
	user_dept = await db_api.update_user_department(
		session,
		department_id=department_id,
		user_id=user_id,
		updated_by=current_user_id,
		**updates,
	)

	if not user_dept:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="User not found in department",
		)

	await session.commit()
	return UserDepartment.model_validate(user_dept)


@router.delete(
	"/{department_id}/members/{user_id}",
	status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_department_member(
	department_id: uuid.UUID,
	user_id: uuid.UUID,
	session: Annotated[AsyncSession, Depends(get_async_session)],
	current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
	"""Remove a user from a department."""
	success = await db_api.remove_user_from_department(
		session,
		department_id=department_id,
		user_id=user_id,
		deleted_by=current_user_id,
	)

	if not success:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="User not found in department",
		)

	await session.commit()


# Access rules
@router.get("/{department_id}/access-rules", response_model=list[DepartmentAccessRule])
async def list_access_rules(
	department_id: uuid.UUID,
	session: Annotated[AsyncSession, Depends(get_async_session)],
):
	"""List department access rules."""
	rules = await db_api.get_department_access_rules(session, department_id)
	return [DepartmentAccessRule.model_validate(r) for r in rules]


@router.post(
	"/{department_id}/access-rules",
	response_model=DepartmentAccessRule,
	status_code=status.HTTP_201_CREATED,
)
async def create_access_rule(
	department_id: uuid.UUID,
	data: DepartmentAccessRuleCreate,
	session: Annotated[AsyncSession, Depends(get_async_session)],
	current_user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
	"""Create an access rule for a department."""
	department = await db_api.get_department(session, department_id)
	if not department:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Department not found",
		)

	rule = await db_api.create_access_rule(
		session,
		department_id=department_id,
		document_type_id=data.document_type_id,
		permission_level=data.permission_level.value,
		can_create=data.can_create,
		can_share=data.can_share,
		inherit_to_children=data.inherit_to_children,
		created_by=current_user_id,
	)
	await session.commit()

	return DepartmentAccessRule.model_validate(rule)


# Effective permissions for a user
@router.get("/users/{user_id}/effective-permissions")
async def get_user_effective_permissions(
	user_id: uuid.UUID,
	session: Annotated[AsyncSession, Depends(get_async_session)],
	document_type_id: uuid.UUID | None = None,
):
	"""Get effective permissions for a user based on department memberships."""
	return await db_api.get_effective_permissions(
		session,
		user_id=user_id,
		document_type_id=document_type_id,
	)
