# (c) Copyright Datacraft, 2026
"""
Policy Evaluation Engine for ABAC/PBAC.

Provides real-time policy evaluation with caching, audit logging,
and support for complex attribute-based conditions.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any

from .models import (
	Policy, PolicyRule, PolicyCondition, PolicyEffect, PolicyStatus,
	ConditionOperator, AttributeCategory
)

logger = logging.getLogger(__name__)


@dataclass
class SubjectAttributes:
	"""Attributes of the subject (user/principal) making the request."""
	id: str
	username: str
	email: str | None = None
	roles: list[str] = field(default_factory=list)
	groups: list[str] = field(default_factory=list)
	department: str | None = None
	department_hierarchy: list[str] = field(default_factory=list)  # ["/org", "/org/dept", "/org/dept/team"]
	tenant_id: str | None = None
	is_superuser: bool = False
	custom_attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceAttributes:
	"""Attributes of the resource being accessed."""
	id: str
	type: str  # document, folder, portfolio, case, etc.
	owner_id: str | None = None
	department: str | None = None
	classification: str | None = None  # public, internal, confidential, restricted
	tags: list[str] = field(default_factory=list)
	tenant_id: str | None = None
	custom_attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvironmentAttributes:
	"""Environmental/contextual attributes."""
	timestamp: datetime = field(default_factory=datetime.utcnow)
	ip_address: str | None = None
	user_agent: str | None = None
	device_type: str | None = None  # desktop, mobile, tablet
	location: str | None = None
	is_internal_network: bool = False
	session_id: str | None = None
	mfa_verified: bool = False
	custom_attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyContext:
	"""Complete context for policy evaluation."""
	subject: SubjectAttributes
	resource: ResourceAttributes
	action: str
	environment: EnvironmentAttributes = field(default_factory=EnvironmentAttributes)
	department_permissions: dict[str, Any] = field(default_factory=dict)  # {"permission_level": "view", ...}

	def get_attribute(self, category: AttributeCategory, attribute: str) -> Any:
		"""Get an attribute value from the context."""
		if category == AttributeCategory.SUBJECT:
			return self._get_from_subject(attribute)
		elif category == AttributeCategory.RESOURCE:
			return self._get_from_resource(attribute)
		elif category == AttributeCategory.ACTION:
			return self.action if attribute == "name" else None
		elif category == AttributeCategory.ENVIRONMENT:
			return self._get_from_environment(attribute)
		return None

	def _get_from_subject(self, attr: str) -> Any:
		if hasattr(self.subject, attr):
			return getattr(self.subject, attr)
		return self.subject.custom_attributes.get(attr)

	def _get_from_resource(self, attr: str) -> Any:
		if hasattr(self.resource, attr):
			return getattr(self.resource, attr)
		return self.resource.custom_attributes.get(attr)

	def _get_from_environment(self, attr: str) -> Any:
		if hasattr(self.environment, attr):
			return getattr(self.environment, attr)
		return self.environment.custom_attributes.get(attr)


@dataclass
class PolicyDecision:
	"""Result of policy evaluation."""
	allowed: bool
	effect: PolicyEffect
	matched_policy: Policy | None = None
	matched_conditions: list[PolicyCondition] = field(default_factory=list)
	reason: str = ""
	evaluation_time_ms: float = 0.0
	audit_id: str | None = None

	def to_dict(self) -> dict:
		return {
			"allowed": self.allowed,
			"effect": self.effect.value,
			"matched_policy_id": self.matched_policy.id if self.matched_policy else None,
			"matched_policy_name": self.matched_policy.name if self.matched_policy else None,
			"reason": self.reason,
			"evaluation_time_ms": self.evaluation_time_ms,
			"audit_id": self.audit_id,
		}


class PolicyEngine:
	"""
	Policy evaluation engine with caching and audit support.

	Evaluation strategy:
	1. Find all applicable policies (matching action and resource type)
	2. Sort by priority (lower = higher priority)
	3. Evaluate each policy until a DENY is found or all ALLOW policies pass
	4. Default to DENY if no policies match
	"""

	def __init__(self, policies: list[Policy] | None = None):
		self._policies: list[Policy] = policies or []
		self._policy_cache: dict[str, list[Policy]] = {}

	def add_policy(self, policy: Policy):
		"""Add a policy to the engine."""
		self._policies.append(policy)
		self._policy_cache.clear()

	def remove_policy(self, policy_id: str):
		"""Remove a policy from the engine."""
		self._policies = [p for p in self._policies if p.id != policy_id]
		self._policy_cache.clear()

	def load_policies(self, policies: list[Policy]):
		"""Load a list of policies, replacing existing ones."""
		self._policies = policies
		self._policy_cache.clear()

	def evaluate(self, context: PolicyContext) -> PolicyDecision:
		"""
		Evaluate policies against the given context.

		Returns a decision with the overall result and audit information.
		"""
		start_time = datetime.utcnow()

		# Superuser bypass
		if context.subject.is_superuser:
			return PolicyDecision(
				allowed=True,
				effect=PolicyEffect.ALLOW,
				reason="Superuser bypass",
				evaluation_time_ms=0.0,
			)

		# Get applicable policies
		applicable = self._get_applicable_policies(
			context.action,
			context.resource.type,
			context.subject.tenant_id,
		)

		if not applicable:
			elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
			return PolicyDecision(
				allowed=False,
				effect=PolicyEffect.DENY,
				reason="No applicable policies found",
				evaluation_time_ms=elapsed,
			)

		# Evaluate policies in priority order
		for policy in applicable:
			result = self._evaluate_policy(policy, context)
			if result is not None:
				elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000

				# DENY takes immediate effect
				if policy.effect == PolicyEffect.DENY and result:
					return PolicyDecision(
						allowed=False,
						effect=PolicyEffect.DENY,
						matched_policy=policy,
						reason=f"Denied by policy: {policy.name}",
						evaluation_time_ms=elapsed,
					)

				# ALLOW only if conditions match
				if policy.effect == PolicyEffect.ALLOW and result:
					return PolicyDecision(
						allowed=True,
						effect=PolicyEffect.ALLOW,
						matched_policy=policy,
						reason=f"Allowed by policy: {policy.name}",
						evaluation_time_ms=elapsed,
					)

		# Check department-level permissions if no policy matched
		if context.department_permissions:
			perm_level = context.department_permissions.get("permission_level", "none")
			permission_order = ["none", "view", "edit", "delete", "admin"]
			
			action_map = {
				"view": "view",
				"read": "view",
				"edit": "edit",
				"update": "edit",
				"delete": "delete",
				"create": "admin", # creation usually requires higher level or specific flag
			}
			
			required_level = action_map.get(context.action.lower(), "view")
			
			if context.action.lower() == "create" and context.department_permissions.get("can_create"):
				elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
				return PolicyDecision(
					allowed=True,
					effect=PolicyEffect.ALLOW,
					reason="Allowed by department creation permission",
					evaluation_time_ms=elapsed,
				)

			if permission_order.index(perm_level) >= permission_order.index(required_level):
				elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
				return PolicyDecision(
					allowed=True,
					effect=PolicyEffect.ALLOW,
					reason=f"Allowed by department permission level: {perm_level}",
					evaluation_time_ms=elapsed,
				)

		# Default deny
		elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
		return PolicyDecision(
			allowed=False,
			effect=PolicyEffect.DENY,
			reason="No matching ALLOW policy",
			evaluation_time_ms=elapsed,
		)

	def _get_applicable_policies(
		self,
		action: str,
		resource_type: str,
		tenant_id: str | None,
	) -> list[Policy]:
		"""Get policies applicable to the given action and resource type."""
		cache_key = f"{action}:{resource_type}:{tenant_id or 'global'}"
		if cache_key in self._policy_cache:
			return self._policy_cache[cache_key]

		applicable = []
		for policy in self._policies:
			# Check status and validity
			if not policy.is_valid_now():
				continue

			# Check tenant scope
			if policy.tenant_id and policy.tenant_id != tenant_id:
				continue

			# Check action match (supports wildcards)
			action_match = any(
				self._matches_pattern(action, a) for a in policy.actions
			)
			if not action_match:
				continue

			# Check resource type match
			resource_match = any(
				self._matches_pattern(resource_type, r) for r in policy.resource_types
			)
			if not resource_match:
				continue

			applicable.append(policy)

		# Sort by priority
		applicable.sort(key=lambda p: p.priority)
		self._policy_cache[cache_key] = applicable
		return applicable

	def _matches_pattern(self, value: str, pattern: str) -> bool:
		"""Check if value matches pattern (supports * wildcard)."""
		if pattern == "*":
			return True
		if "*" in pattern:
			regex = pattern.replace(".", r"\.").replace("*", ".*")
			return bool(re.match(f"^{regex}$", value))
		return value == pattern

	def _evaluate_policy(self, policy: Policy, context: PolicyContext) -> bool | None:
		"""
		Evaluate a single policy against the context.

		Returns:
			True if all conditions match
			False if any condition fails
			None if policy doesn't apply
		"""
		if not policy.rules:
			# Policy with no conditions always matches
			return True

		for rule in policy.rules:
			rule_result = self._evaluate_rule(rule, context)
			if rule_result:
				return True

		return False

	def _evaluate_rule(self, rule: PolicyRule, context: PolicyContext) -> bool:
		"""Evaluate a policy rule (set of conditions with AND/OR logic)."""
		if not rule.conditions:
			return True

		results = [self._evaluate_condition(c, context) for c in rule.conditions]

		if rule.logic == "AND":
			return all(results)
		elif rule.logic == "OR":
			return any(results)

		return False

	def _evaluate_condition(self, condition: PolicyCondition, context: PolicyContext) -> bool:
		"""Evaluate a single condition."""
		actual = context.get_attribute(condition.category, condition.attribute)
		expected = condition.value

		# Handle attribute references (e.g., resource.department matching subject.department)
		if isinstance(expected, str) and "." in expected:
			parts = expected.split(".", 1)
			if len(parts) == 2 and parts[0] in ("subject", "resource", "environment"):
				cat = AttributeCategory(parts[0])
				expected = context.get_attribute(cat, parts[1])

		return self._compare(actual, condition.operator, expected)

	def _compare(self, actual: Any, operator: ConditionOperator, expected: Any) -> bool:
		"""Compare values using the given operator."""
		if actual is None and operator not in (ConditionOperator.EXISTS, ConditionOperator.NOT_EXISTS):
			return False

		match operator:
			case ConditionOperator.EQUALS:
				return actual == expected
			case ConditionOperator.NOT_EQUALS:
				return actual != expected
			case ConditionOperator.GREATER_THAN:
				return actual > expected
			case ConditionOperator.GREATER_THAN_OR_EQUAL:
				return actual >= expected
			case ConditionOperator.LESS_THAN:
				return actual < expected
			case ConditionOperator.LESS_THAN_OR_EQUAL:
				return actual <= expected
			case ConditionOperator.IN:
				return actual in expected if isinstance(expected, (list, tuple, set)) else actual == expected
			case ConditionOperator.NOT_IN:
				return actual not in expected if isinstance(expected, (list, tuple, set)) else actual != expected
			case ConditionOperator.CONTAINS:
				if isinstance(actual, str):
					return expected in actual
				if isinstance(actual, (list, tuple, set)):
					return expected in actual
				return False
			case ConditionOperator.NOT_CONTAINS:
				if isinstance(actual, str):
					return expected not in actual
				if isinstance(actual, (list, tuple, set)):
					return expected not in actual
				return True
			case ConditionOperator.STARTS_WITH:
				return isinstance(actual, str) and actual.startswith(expected)
			case ConditionOperator.ENDS_WITH:
				return isinstance(actual, str) and actual.endswith(expected)
			case ConditionOperator.MATCHES:
				return isinstance(actual, str) and bool(re.match(expected, actual))
			case ConditionOperator.EXISTS:
				return actual is not None
			case ConditionOperator.NOT_EXISTS:
				return actual is None
			case ConditionOperator.IS_MEMBER_OF:
				# Check group membership
				if not hasattr(actual, '__iter__'):
					return False
				return expected in actual
			case ConditionOperator.HAS_ROLE:
				# Check role
				subject = actual  # Should be roles list
				if isinstance(subject, list):
					return expected in subject
				return False
			case ConditionOperator.IN_DEPARTMENT:
				return actual == expected
			case ConditionOperator.IN_DEPARTMENT_HIERARCHY:
				# Check if actual is in expected hierarchy
				if isinstance(expected, list):
					return actual in expected
				if isinstance(actual, list):
					return expected in actual
				return str(actual).startswith(str(expected))
			case _:
				logger.warning(f"Unknown operator: {operator}")
				return False


class DepartmentIsolationEngine:
	"""
	Engine for department-based access isolation.

	Ensures users can only access resources within their department
	hierarchy unless explicitly granted cross-department access.
	"""

	def __init__(self):
		self._cross_department_permissions: dict[str, set[str]] = {}  # user_id -> set of department_ids

	def grant_cross_department_access(self, user_id: str, department_id: str):
		"""Grant a user access to another department."""
		if user_id not in self._cross_department_permissions:
			self._cross_department_permissions[user_id] = set()
		self._cross_department_permissions[user_id].add(department_id)

	def revoke_cross_department_access(self, user_id: str, department_id: str):
		"""Revoke cross-department access."""
		if user_id in self._cross_department_permissions:
			self._cross_department_permissions[user_id].discard(department_id)

	def can_access_department(
		self,
		subject: SubjectAttributes,
		target_department: str,
	) -> bool:
		"""Check if subject can access resources in target department."""
		if subject.is_superuser:
			return True

		# Same department
		if subject.department == target_department:
			return True

		# In hierarchy (parent department can see child departments)
		if subject.department_hierarchy:
			for dept in subject.department_hierarchy:
				if target_department.startswith(dept):
					return True

		# Explicit cross-department permission
		if subject.id in self._cross_department_permissions:
			if target_department in self._cross_department_permissions[subject.id]:
				return True

		return False

	def filter_by_department(
		self,
		subject: SubjectAttributes,
		resources: list[ResourceAttributes],
	) -> list[ResourceAttributes]:
		"""Filter resources to only those the subject can access."""
		return [
			r for r in resources
			if not r.department or self.can_access_department(subject, r.department)
		]
