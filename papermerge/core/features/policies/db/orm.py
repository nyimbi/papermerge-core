# (c) Copyright Datacraft, 2026
"""SQLAlchemy ORM models for policy system."""
from datetime import datetime
from sqlalchemy import (
	Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Enum, JSON, Index
)
from sqlalchemy.orm import relationship
from uuid_extensions import uuid7str

from papermerge.core.db.base import Base
from ..models import PolicyEffect, PolicyStatus


class PolicyModel(Base):
	"""Persisted policy definition."""
	__tablename__ = "policies"

	id = Column(String(36), primary_key=True, default=uuid7str)
	name = Column(String(255), nullable=False)
	description = Column(Text, default="")
	effect = Column(Enum(PolicyEffect), nullable=False)
	priority = Column(Integer, default=100)
	rules_json = Column(JSON, default=list)
	actions = Column(JSON, default=list)  # List of action strings
	resource_types = Column(JSON, default=list)  # List of resource type strings
	status = Column(Enum(PolicyStatus), default=PolicyStatus.DRAFT)
	tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
	created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
	created_at = Column(DateTime, default=datetime.utcnow)
	updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
	valid_from = Column(DateTime, nullable=True)
	valid_until = Column(DateTime, nullable=True)
	dsl_text = Column(Text, nullable=True)  # Original DSL if parsed from text
	metadata_json = Column(JSON, default=dict)

	tenant = relationship("Tenant", back_populates="policies")
	creator = relationship("User", foreign_keys=[created_by])
	approvals = relationship("PolicyApprovalModel", back_populates="policy", cascade="all, delete-orphan")
	evaluation_logs = relationship("PolicyEvaluationLogModel", back_populates="policy", cascade="all, delete-orphan")

	__table_args__ = (
		Index("ix_policies_tenant_status", "tenant_id", "status"),
		Index("ix_policies_effect_priority", "effect", "priority"),
	)


class PolicyApprovalModel(Base):
	"""Policy approval workflow record."""
	__tablename__ = "policy_approvals"

	id = Column(String(36), primary_key=True, default=uuid7str)
	policy_id = Column(String(36), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False)
	requested_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
	requested_at = Column(DateTime, default=datetime.utcnow)
	status = Column(String(20), default="pending")  # pending, approved, rejected
	reviewed_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
	reviewed_at = Column(DateTime, nullable=True)
	comments = Column(Text, nullable=True)
	policy_snapshot = Column(JSON, default=dict)  # Policy state at request time
	changes_summary = Column(Text, nullable=True)  # Human-readable change summary

	policy = relationship("PolicyModel", back_populates="approvals")
	requester = relationship("User", foreign_keys=[requested_by])
	reviewer = relationship("User", foreign_keys=[reviewed_by])

	__table_args__ = (
		Index("ix_policy_approvals_status", "status"),
		Index("ix_policy_approvals_policy_id", "policy_id"),
	)


class PolicyEvaluationLogModel(Base):
	"""Audit log of policy evaluation decisions."""
	__tablename__ = "policy_evaluation_logs"

	id = Column(String(36), primary_key=True, default=uuid7str)
	policy_id = Column(String(36), ForeignKey("policies.id", ondelete="SET NULL"), nullable=True)
	timestamp = Column(DateTime, default=datetime.utcnow, index=True)

	# Request context
	subject_id = Column(String(36), nullable=False)
	subject_username = Column(String(255), nullable=True)
	resource_id = Column(String(36), nullable=False)
	resource_type = Column(String(50), nullable=False)
	action = Column(String(50), nullable=False)

	# Decision
	allowed = Column(Boolean, nullable=False)
	effect = Column(Enum(PolicyEffect), nullable=False)
	reason = Column(Text, nullable=True)
	evaluation_time_ms = Column(Integer, default=0)

	# Context snapshot for forensics
	context_snapshot = Column(JSON, default=dict)
	tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)

	policy = relationship("PolicyModel", back_populates="evaluation_logs")

	__table_args__ = (
		Index("ix_policy_eval_logs_subject_action", "subject_id", "action"),
		Index("ix_policy_eval_logs_resource", "resource_id", "resource_type"),
		Index("ix_policy_eval_logs_tenant_time", "tenant_id", "timestamp"),
	)


class DepartmentAccessModel(Base):
	"""Cross-department access grants."""
	__tablename__ = "department_access_grants"

	id = Column(String(36), primary_key=True, default=uuid7str)
	user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
	department_id = Column(String(36), nullable=False)
	granted_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
	granted_at = Column(DateTime, default=datetime.utcnow)
	expires_at = Column(DateTime, nullable=True)
	reason = Column(Text, nullable=True)
	tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)

	user = relationship("User", foreign_keys=[user_id])
	granter = relationship("User", foreign_keys=[granted_by])

	__table_args__ = (
		Index("ix_dept_access_user_dept", "user_id", "department_id"),
		Index("ix_dept_access_expires", "expires_at"),
	)
