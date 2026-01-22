# (c) Copyright Datacraft, 2026
"""Pydantic schemas for policy API."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from typing import Any
from uuid_extensions import uuid7str

from .models import PolicyEffect, PolicyStatus, ConditionOperator, AttributeCategory


class PolicyConditionSchema(BaseModel):
	"""Schema for a policy condition."""
	model_config = ConfigDict(extra="forbid")

	category: AttributeCategory
	attribute: str
	operator: ConditionOperator
	value: Any


class PolicyRuleSchema(BaseModel):
	"""Schema for a policy rule."""
	model_config = ConfigDict(extra="forbid")

	conditions: list[PolicyConditionSchema]
	logic: str = "AND"


class PolicyCreate(BaseModel):
	"""Schema for creating a policy."""
	model_config = ConfigDict(extra="forbid")

	name: str = Field(..., min_length=1, max_length=255)
	description: str = ""
	effect: PolicyEffect
	priority: int = Field(default=100, ge=0, le=1000)
	rules: list[PolicyRuleSchema] = Field(default_factory=list)
	actions: list[str] = Field(..., min_length=1)
	resource_types: list[str] = Field(..., min_length=1)
	valid_from: datetime | None = None
	valid_until: datetime | None = None
	metadata: dict = Field(default_factory=dict)


class PolicyCreateFromDSL(BaseModel):
	"""Schema for creating a policy from DSL text."""
	model_config = ConfigDict(extra="forbid")

	name: str = Field(..., min_length=1, max_length=255)
	description: str = ""
	dsl_text: str = Field(..., min_length=1)
	priority: int = Field(default=100, ge=0, le=1000)
	valid_from: datetime | None = None
	valid_until: datetime | None = None


class PolicyUpdate(BaseModel):
	"""Schema for updating a policy."""
	model_config = ConfigDict(extra="forbid")

	name: str | None = None
	description: str | None = None
	effect: PolicyEffect | None = None
	priority: int | None = Field(default=None, ge=0, le=1000)
	rules: list[PolicyRuleSchema] | None = None
	actions: list[str] | None = None
	resource_types: list[str] | None = None
	status: PolicyStatus | None = None
	valid_from: datetime | None = None
	valid_until: datetime | None = None
	metadata: dict | None = None


class PolicyResponse(BaseModel):
	"""Schema for policy response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	name: str
	description: str
	effect: PolicyEffect
	priority: int
	rules: list[PolicyRuleSchema]
	actions: list[str]
	resource_types: list[str]
	status: PolicyStatus
	tenant_id: str | None
	created_by: str | None
	created_at: datetime
	updated_at: datetime
	valid_from: datetime | None
	valid_until: datetime | None
	dsl_text: str | None = None


class PolicyListResponse(BaseModel):
	"""Schema for policy list response."""
	items: list[PolicyResponse]
	total: int
	limit: int
	offset: int


class ApprovalRequestCreate(BaseModel):
	"""Schema for creating an approval request."""
	model_config = ConfigDict(extra="forbid")

	changes_summary: str | None = None


class ApprovalAction(BaseModel):
	"""Schema for approval/rejection action."""
	model_config = ConfigDict(extra="forbid")

	comments: str | None = None


class ApprovalResponse(BaseModel):
	"""Schema for approval response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	policy_id: str
	requested_by: str | None
	requested_at: datetime
	status: str
	reviewed_by: str | None = None
	reviewed_at: datetime | None = None
	comments: str | None = None
	changes_summary: str | None = None
	policy_name: str | None = None


class EvaluationLogResponse(BaseModel):
	"""Schema for evaluation log response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	policy_id: str | None
	timestamp: datetime
	subject_id: str
	subject_username: str | None
	resource_id: str
	resource_type: str
	action: str
	allowed: bool
	effect: PolicyEffect
	reason: str | None
	evaluation_time_ms: int


class EvaluateRequest(BaseModel):
	"""Schema for policy evaluation request."""
	model_config = ConfigDict(extra="forbid")

	subject_id: str
	subject_username: str | None = None
	subject_roles: list[str] = Field(default_factory=list)
	subject_groups: list[str] = Field(default_factory=list)
	subject_department: str | None = None
	resource_id: str
	resource_type: str
	resource_owner_id: str | None = None
	resource_department: str | None = None
	resource_classification: str | None = None
	action: str
	ip_address: str | None = None
	mfa_verified: bool = False


class EvaluateResponse(BaseModel):
	"""Schema for policy evaluation response."""
	allowed: bool
	effect: PolicyEffect
	matched_policy_id: str | None = None
	matched_policy_name: str | None = None
	reason: str
	evaluation_time_ms: float


class DepartmentAccessGrant(BaseModel):
	"""Schema for granting department access."""
	model_config = ConfigDict(extra="forbid")

	user_id: str
	department_id: str
	expires_at: datetime | None = None
	reason: str | None = None


class DepartmentAccessResponse(BaseModel):
	"""Schema for department access response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	user_id: str
	department_id: str
	granted_by: str | None
	granted_at: datetime
	expires_at: datetime | None
	reason: str | None


class PolicyAnalytics(BaseModel):
	"""Schema for policy analytics."""
	total_policies: int
	active_policies: int
	pending_approvals: int
	evaluations_today: int
	allow_rate: float
	deny_rate: float
	top_denied_actions: list[dict]
	evaluation_latency_avg_ms: float
