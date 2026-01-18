# (c) Copyright Datacraft, 2026
"""Departments ORM models."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from papermerge.core.db.audit_cols import AuditColumns
from papermerge.core.db.base import Base

if TYPE_CHECKING:
	from papermerge.core.features.users.db.orm import User
	from papermerge.core.features.document_types.db.orm import DocumentType


class Department(Base, AuditColumns):
	"""Department model for organizational hierarchy."""
	__tablename__ = "departments"

	id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	code: Mapped[str | None] = mapped_column(String(50), nullable=True)
	description: Mapped[str | None] = mapped_column(Text, nullable=True)
	parent_id: Mapped[uuid.UUID | None] = mapped_column(
		ForeignKey("departments.id", ondelete="SET NULL"),
		nullable=True
	)
	is_active: Mapped[bool] = mapped_column(default=True)

	# Self-referential relationship for hierarchy
	parent: Mapped["Department | None"] = relationship(
		"Department",
		remote_side="Department.id",
		back_populates="children",
		foreign_keys=[parent_id]
	)
	children: Mapped[list["Department"]] = relationship(
		"Department",
		back_populates="parent",
		foreign_keys=[parent_id]
	)

	# User memberships
	user_departments: Mapped[list["UserDepartment"]] = relationship(
		"UserDepartment",
		back_populates="department",
		cascade="all, delete-orphan"
	)

	# Access rules
	access_rules: Mapped[list["DepartmentAccessRule"]] = relationship(
		"DepartmentAccessRule",
		back_populates="department",
		cascade="all, delete-orphan"
	)

	@property
	def members(self) -> list["UserDepartment"]:
		"""Get active department members."""
		return [ud for ud in self.user_departments if ud.deleted_at is None]

	@property
	def head_users(self) -> list["UserDepartment"]:
		"""Get department heads."""
		return [ud for ud in self.members if ud.is_head]

	@property
	def member_count(self) -> int:
		"""Count of active members."""
		return len(self.members)

	def __repr__(self) -> str:
		return f"Department({self.id=}, {self.name=}, {self.code=})"

	__table_args__ = (
		CheckConstraint(
			"char_length(trim(name)) > 0",
			name="department_name_not_empty"
		),
		Index(
			"idx_departments_name_active_unique",
			"name",
			unique=True,
			postgresql_where=text("deleted_at IS NULL")
		),
		Index(
			"idx_departments_code_active_unique",
			"code",
			unique=True,
			postgresql_where=text("deleted_at IS NULL AND code IS NOT NULL")
		),
		Index("idx_departments_parent_id", "parent_id"),
		Index("idx_departments_is_active", "is_active"),
	)

	__mapper_args__ = {"confirm_deleted_rows": False}


class UserDepartment(Base, AuditColumns):
	"""User's membership in a department."""
	__tablename__ = "user_departments"

	id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	user_id: Mapped[uuid.UUID] = mapped_column(
		ForeignKey("users.id", ondelete="CASCADE"),
		nullable=False
	)
	department_id: Mapped[uuid.UUID] = mapped_column(
		ForeignKey("departments.id", ondelete="CASCADE"),
		nullable=False
	)
	is_head: Mapped[bool] = mapped_column(default=False)
	is_primary: Mapped[bool] = mapped_column(default=False)
	joined_at: Mapped[datetime | None] = mapped_column(nullable=True)

	# Relationships
	user: Mapped["User"] = relationship(
		"User",
		back_populates="user_departments",
		foreign_keys=[user_id]
	)
	department: Mapped["Department"] = relationship(
		"Department",
		back_populates="user_departments",
		foreign_keys=[department_id]
	)

	def __repr__(self) -> str:
		return f"UserDepartment({self.user_id=}, {self.department_id=}, {self.is_head=})"

	__table_args__ = (
		Index(
			"idx_user_departments_unique",
			"user_id",
			"department_id",
			unique=True,
			postgresql_where=text("deleted_at IS NULL")
		),
		Index("idx_user_departments_user_id", "user_id"),
		Index("idx_user_departments_department_id", "department_id"),
		Index("idx_user_departments_is_head", "is_head"),
	)

	__mapper_args__ = {"confirm_deleted_rows": False}


class DepartmentAccessRule(Base, AuditColumns):
	"""Access rules defining what document types a department can access."""
	__tablename__ = "department_access_rules"

	id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	department_id: Mapped[uuid.UUID] = mapped_column(
		ForeignKey("departments.id", ondelete="CASCADE"),
		nullable=False
	)
	document_type_id: Mapped[uuid.UUID | None] = mapped_column(
		ForeignKey("document_types.id", ondelete="CASCADE"),
		nullable=True  # NULL means all document types
	)
	permission_level: Mapped[str] = mapped_column(
		String(20),
		default="view"
	)  # none, view, edit, delete, admin
	can_create: Mapped[bool] = mapped_column(default=False)
	can_share: Mapped[bool] = mapped_column(default=False)
	inherit_to_children: Mapped[bool] = mapped_column(default=True)

	# Relationships
	department: Mapped["Department"] = relationship(
		"Department",
		back_populates="access_rules",
		foreign_keys=[department_id]
	)
	document_type: Mapped["DocumentType | None"] = relationship(
		"DocumentType",
		foreign_keys=[document_type_id]
	)

	def __repr__(self) -> str:
		return f"DepartmentAccessRule({self.department_id=}, {self.document_type_id=}, {self.permission_level=})"

	__table_args__ = (
		Index(
			"idx_department_access_rules_unique",
			"department_id",
			"document_type_id",
			unique=True,
			postgresql_where=text("deleted_at IS NULL")
		),
		Index("idx_department_access_rules_department_id", "department_id"),
		Index("idx_department_access_rules_document_type_id", "document_type_id"),
		CheckConstraint(
			"permission_level IN ('none', 'view', 'edit', 'delete', 'admin')",
			name="valid_permission_level"
		),
	)

	__mapper_args__ = {"confirm_deleted_rows": False}
