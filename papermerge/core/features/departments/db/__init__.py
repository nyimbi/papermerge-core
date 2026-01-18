# (c) Copyright Datacraft, 2026
"""Departments database models and operations."""

from .orm import Department, UserDepartment, DepartmentAccessRule

__all__ = [
	"Department",
	"UserDepartment",
	"DepartmentAccessRule",
]
