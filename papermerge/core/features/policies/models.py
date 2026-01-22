# (c) Copyright Datacraft, 2026
"""Policy domain models for ABAC/PBAC system."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class PolicyEffect(str, Enum):
	"""Policy decision effect."""
	ALLOW = "allow"
	DENY = "deny"


class PolicyStatus(str, Enum):
	"""Policy lifecycle status."""
	DRAFT = "draft"
	PENDING_APPROVAL = "pending_approval"
	ACTIVE = "active"
	INACTIVE = "inactive"
	ARCHIVED = "archived"


class ConditionOperator(str, Enum):
	"""Operators for policy conditions."""
	EQUALS = "eq"
	NOT_EQUALS = "ne"
	GREATER_THAN = "gt"
	GREATER_THAN_OR_EQUAL = "gte"
	LESS_THAN = "lt"
	LESS_THAN_OR_EQUAL = "lte"
	IN = "in"
	NOT_IN = "not_in"
	CONTAINS = "contains"
	NOT_CONTAINS = "not_contains"
	STARTS_WITH = "starts_with"
	ENDS_WITH = "ends_with"
	MATCHES = "matches"  # Regex
	EXISTS = "exists"
	NOT_EXISTS = "not_exists"
	IS_MEMBER_OF = "is_member_of"  # Group membership
	HAS_ROLE = "has_role"
	IN_DEPARTMENT = "in_department"
	IN_DEPARTMENT_HIERARCHY = "in_department_hierarchy"


class AttributeCategory(str, Enum):
	"""Categories for attributes used in policies."""
	SUBJECT = "subject"      # User/principal attributes
	RESOURCE = "resource"    # Document/node attributes
	ACTION = "action"        # Operation being performed
	ENVIRONMENT = "environment"  # Context: time, IP, device


@dataclass
class PolicyCondition:
	"""Single condition in a policy rule."""
	category: AttributeCategory
	attribute: str
	operator: ConditionOperator
	value: Any

	def to_dict(self) -> dict:
		return {
			"category": self.category.value,
			"attribute": self.attribute,
			"operator": self.operator.value,
			"value": self.value,
		}

	@classmethod
	def from_dict(cls, data: dict) -> "PolicyCondition":
		return cls(
			category=AttributeCategory(data["category"]),
			attribute=data["attribute"],
			operator=ConditionOperator(data["operator"]),
			value=data["value"],
		)


@dataclass
class PolicyRule:
	"""Rule within a policy combining conditions with logical operators."""
	conditions: list[PolicyCondition]
	logic: str = "AND"  # AND, OR

	def to_dict(self) -> dict:
		return {
			"conditions": [c.to_dict() for c in self.conditions],
			"logic": self.logic,
		}

	@classmethod
	def from_dict(cls, data: dict) -> "PolicyRule":
		return cls(
			conditions=[PolicyCondition.from_dict(c) for c in data["conditions"]],
			logic=data.get("logic", "AND"),
		)


@dataclass
class Policy:
	"""Complete policy definition."""
	id: str
	name: str
	description: str
	effect: PolicyEffect
	priority: int  # Lower = higher priority
	rules: list[PolicyRule]
	actions: list[str]  # Actions this policy applies to
	resource_types: list[str]  # Resource types this applies to
	status: PolicyStatus = PolicyStatus.DRAFT
	tenant_id: str | None = None
	created_by: str | None = None
	created_at: datetime = field(default_factory=datetime.utcnow)
	updated_at: datetime = field(default_factory=datetime.utcnow)
	valid_from: datetime | None = None
	valid_until: datetime | None = None
	metadata: dict = field(default_factory=dict)

	def to_dict(self) -> dict:
		return {
			"id": self.id,
			"name": self.name,
			"description": self.description,
			"effect": self.effect.value,
			"priority": self.priority,
			"rules": [r.to_dict() for r in self.rules],
			"actions": self.actions,
			"resource_types": self.resource_types,
			"status": self.status.value,
			"tenant_id": self.tenant_id,
			"created_by": self.created_by,
			"created_at": self.created_at.isoformat() if self.created_at else None,
			"updated_at": self.updated_at.isoformat() if self.updated_at else None,
			"valid_from": self.valid_from.isoformat() if self.valid_from else None,
			"valid_until": self.valid_until.isoformat() if self.valid_until else None,
			"metadata": self.metadata,
		}

	@classmethod
	def from_dict(cls, data: dict) -> "Policy":
		return cls(
			id=data["id"],
			name=data["name"],
			description=data.get("description", ""),
			effect=PolicyEffect(data["effect"]),
			priority=data.get("priority", 100),
			rules=[PolicyRule.from_dict(r) for r in data.get("rules", [])],
			actions=data.get("actions", []),
			resource_types=data.get("resource_types", []),
			status=PolicyStatus(data.get("status", "draft")),
			tenant_id=data.get("tenant_id"),
			created_by=data.get("created_by"),
			created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
			updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
			valid_from=datetime.fromisoformat(data["valid_from"]) if data.get("valid_from") else None,
			valid_until=datetime.fromisoformat(data["valid_until"]) if data.get("valid_until") else None,
			metadata=data.get("metadata", {}),
		)

	def is_valid_now(self) -> bool:
		"""Check if policy is currently valid based on time constraints."""
		now = datetime.utcnow()
		if self.valid_from and now < self.valid_from:
			return False
		if self.valid_until and now > self.valid_until:
			return False
		return self.status == PolicyStatus.ACTIVE


@dataclass
class PolicyApproval:
	"""Approval record for policy changes."""
	id: str
	policy_id: str
	requested_by: str
	requested_at: datetime
	status: str  # pending, approved, rejected
	reviewed_by: str | None = None
	reviewed_at: datetime | None = None
	comments: str | None = None
	policy_snapshot: dict = field(default_factory=dict)  # Policy state at request time
