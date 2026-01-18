# (c) Copyright Datacraft, 2026
"""Departments database API."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from .orm import Department, DepartmentAccessRule, UserDepartment


async def get_department(
	session: AsyncSession,
	department_id: uuid.UUID,
) -> Department | None:
	"""Get department by ID."""
	stmt = (
		select(Department)
		.options(
			selectinload(Department.parent),
			selectinload(Department.children),
			selectinload(Department.user_departments).selectinload(UserDepartment.user),
			selectinload(Department.access_rules),
		)
		.where(
			and_(
				Department.id == department_id,
				Department.deleted_at.is_(None),
			)
		)
	)
	result = await session.execute(stmt)
	return result.scalar_one_or_none()


async def get_department_by_code(
	session: AsyncSession,
	code: str,
) -> Department | None:
	"""Get department by code."""
	stmt = (
		select(Department)
		.where(
			and_(
				Department.code == code,
				Department.deleted_at.is_(None),
			)
		)
	)
	result = await session.execute(stmt)
	return result.scalar_one_or_none()


async def list_departments(
	session: AsyncSession,
	page_size: int = 25,
	page_number: int = 1,
	sort_by: str | None = None,
	sort_direction: str | None = None,
	filters: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[Department], int]:
	"""List departments with pagination and filtering."""
	stmt = (
		select(Department)
		.options(selectinload(Department.user_departments))
		.where(Department.deleted_at.is_(None))
	)

	# Apply filters
	if filters:
		if "parent_id" in filters:
			parent_id = filters["parent_id"]["value"]
			if parent_id is None:
				stmt = stmt.where(Department.parent_id.is_(None))
			else:
				stmt = stmt.where(Department.parent_id == parent_id)

		if "is_active" in filters:
			stmt = stmt.where(Department.is_active == filters["is_active"]["value"])

		if "free_text" in filters:
			search_term = f"%{filters['free_text']['value']}%"
			stmt = stmt.where(
				or_(
					Department.name.ilike(search_term),
					Department.code.ilike(search_term),
					Department.description.ilike(search_term),
				)
			)

	# Count total
	count_stmt = select(func.count()).select_from(stmt.subquery())
	count_result = await session.execute(count_stmt)
	total = count_result.scalar_one()

	# Sorting
	sort_column = getattr(Department, sort_by, Department.name) if sort_by else Department.name
	if sort_direction == "desc":
		stmt = stmt.order_by(sort_column.desc())
	else:
		stmt = stmt.order_by(sort_column.asc())

	# Pagination
	offset = (page_number - 1) * page_size
	stmt = stmt.offset(offset).limit(page_size)

	result = await session.execute(stmt)
	departments = list(result.scalars().all())

	return departments, total


async def get_department_tree(
	session: AsyncSession,
	root_id: uuid.UUID | None = None,
) -> list[Department]:
	"""Get department hierarchy as tree."""
	stmt = (
		select(Department)
		.options(
			selectinload(Department.children),
			selectinload(Department.user_departments).selectinload(UserDepartment.user),
		)
		.where(Department.deleted_at.is_(None))
	)

	if root_id:
		stmt = stmt.where(Department.id == root_id)
	else:
		stmt = stmt.where(Department.parent_id.is_(None))

	result = await session.execute(stmt)
	return list(result.scalars().all())


async def create_department(
	session: AsyncSession,
	name: str,
	code: str | None = None,
	description: str | None = None,
	parent_id: uuid.UUID | None = None,
	created_by: uuid.UUID | None = None,
) -> Department:
	"""Create a new department."""
	now = datetime.now(timezone.utc)
	department = Department(
		name=name,
		code=code,
		description=description,
		parent_id=parent_id,
		is_active=True,
		created_at=now,
		updated_at=now,
		created_by=created_by,
		updated_by=created_by,
	)
	session.add(department)
	await session.flush()
	await session.refresh(department)
	return department


async def update_department(
	session: AsyncSession,
	department_id: uuid.UUID,
	updated_by: uuid.UUID | None = None,
	**updates: Any,
) -> Department | None:
	"""Update a department."""
	department = await get_department(session, department_id)
	if not department:
		return None

	now = datetime.now(timezone.utc)

	for key, value in updates.items():
		if value is not None and hasattr(department, key):
			setattr(department, key, value)

	department.updated_at = now
	department.updated_by = updated_by

	await session.flush()
	await session.refresh(department)
	return department


async def delete_department(
	session: AsyncSession,
	department_id: uuid.UUID,
	deleted_by: uuid.UUID | None = None,
) -> bool:
	"""Soft delete a department."""
	department = await get_department(session, department_id)
	if not department:
		return False

	now = datetime.now(timezone.utc)
	department.deleted_at = now
	department.deleted_by = deleted_by

	await session.flush()
	return True


async def add_user_to_department(
	session: AsyncSession,
	department_id: uuid.UUID,
	user_id: uuid.UUID,
	is_head: bool = False,
	is_primary: bool = False,
	created_by: uuid.UUID | None = None,
) -> UserDepartment:
	"""Add a user to a department."""
	now = datetime.now(timezone.utc)
	user_dept = UserDepartment(
		user_id=user_id,
		department_id=department_id,
		is_head=is_head,
		is_primary=is_primary,
		joined_at=now,
		created_at=now,
		updated_at=now,
		created_by=created_by,
		updated_by=created_by,
	)
	session.add(user_dept)
	await session.flush()
	await session.refresh(user_dept)
	return user_dept


async def remove_user_from_department(
	session: AsyncSession,
	department_id: uuid.UUID,
	user_id: uuid.UUID,
	deleted_by: uuid.UUID | None = None,
) -> bool:
	"""Remove a user from a department (soft delete)."""
	stmt = select(UserDepartment).where(
		and_(
			UserDepartment.department_id == department_id,
			UserDepartment.user_id == user_id,
			UserDepartment.deleted_at.is_(None),
		)
	)
	result = await session.execute(stmt)
	user_dept = result.scalar_one_or_none()

	if not user_dept:
		return False

	now = datetime.now(timezone.utc)
	user_dept.deleted_at = now
	user_dept.deleted_by = deleted_by

	await session.flush()
	return True


async def update_user_department(
	session: AsyncSession,
	department_id: uuid.UUID,
	user_id: uuid.UUID,
	updated_by: uuid.UUID | None = None,
	**updates: Any,
) -> UserDepartment | None:
	"""Update user's department membership."""
	stmt = select(UserDepartment).where(
		and_(
			UserDepartment.department_id == department_id,
			UserDepartment.user_id == user_id,
			UserDepartment.deleted_at.is_(None),
		)
	)
	result = await session.execute(stmt)
	user_dept = result.scalar_one_or_none()

	if not user_dept:
		return None

	now = datetime.now(timezone.utc)

	for key, value in updates.items():
		if value is not None and hasattr(user_dept, key):
			setattr(user_dept, key, value)

	user_dept.updated_at = now
	user_dept.updated_by = updated_by

	await session.flush()
	await session.refresh(user_dept)
	return user_dept


async def get_user_departments(
	session: AsyncSession,
	user_id: uuid.UUID,
) -> list[UserDepartment]:
	"""Get all departments a user belongs to."""
	stmt = (
		select(UserDepartment)
		.options(selectinload(UserDepartment.department))
		.where(
			and_(
				UserDepartment.user_id == user_id,
				UserDepartment.deleted_at.is_(None),
			)
		)
	)
	result = await session.execute(stmt)
	return list(result.scalars().all())


async def create_access_rule(
	session: AsyncSession,
	department_id: uuid.UUID,
	document_type_id: uuid.UUID | None = None,
	permission_level: str = "view",
	can_create: bool = False,
	can_share: bool = False,
	inherit_to_children: bool = True,
	created_by: uuid.UUID | None = None,
) -> DepartmentAccessRule:
	"""Create an access rule for a department."""
	now = datetime.now(timezone.utc)
	rule = DepartmentAccessRule(
		department_id=department_id,
		document_type_id=document_type_id,
		permission_level=permission_level,
		can_create=can_create,
		can_share=can_share,
		inherit_to_children=inherit_to_children,
		created_at=now,
		updated_at=now,
		created_by=created_by,
		updated_by=created_by,
	)
	session.add(rule)
	await session.flush()
	await session.refresh(rule)
	return rule


async def get_department_access_rules(
	session: AsyncSession,
	department_id: uuid.UUID,
) -> list[DepartmentAccessRule]:
	"""Get all access rules for a department."""
	stmt = (
		select(DepartmentAccessRule)
		.where(
			and_(
				DepartmentAccessRule.department_id == department_id,
				DepartmentAccessRule.deleted_at.is_(None),
			)
		)
	)
	result = await session.execute(stmt)
	return list(result.scalars().all())


async def get_effective_permissions(
	session: AsyncSession,
	user_id: uuid.UUID,
	document_type_id: uuid.UUID | None = None,
) -> dict[str, Any]:
	"""Get effective permissions for a user based on their department memberships."""
	# Get user's departments
	user_depts = await get_user_departments(session, user_id)

	permissions = {
		"permission_level": "none",
		"can_create": False,
		"can_share": False,
		"departments": [],
	}

	permission_order = ["none", "view", "edit", "delete", "admin"]

	for user_dept in user_depts:
		dept = user_dept.department

		# Get access rules for this department
		rules = await get_department_access_rules(session, dept.id)

		for rule in rules:
			# Check if rule applies (None means all document types)
			if rule.document_type_id is None or rule.document_type_id == document_type_id:
				# Take highest permission level
				current_level = permission_order.index(permissions["permission_level"])
				rule_level = permission_order.index(rule.permission_level)
				if rule_level > current_level:
					permissions["permission_level"] = rule.permission_level

				# OR the boolean permissions
				permissions["can_create"] = permissions["can_create"] or rule.can_create
				permissions["can_share"] = permissions["can_share"] or rule.can_share

		permissions["departments"].append({
			"id": str(dept.id),
			"name": dept.name,
			"is_head": user_dept.is_head,
		})

	return permissions
