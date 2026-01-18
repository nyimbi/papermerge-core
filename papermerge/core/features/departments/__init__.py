# (c) Copyright Datacraft, 2026
"""Departments feature for hierarchical organizational structure."""

from .schema import (
	Department,
	DepartmentCreate,
	DepartmentUpdate,
	DepartmentDetails,
	DepartmentTree,
	UserDepartment,
	DepartmentAccessRule,
	PermissionLevel,
)

__all__ = [
	"Department",
	"DepartmentCreate",
	"DepartmentUpdate",
	"DepartmentDetails",
	"DepartmentTree",
	"UserDepartment",
	"DepartmentAccessRule",
	"PermissionLevel",
]
