# (c) Copyright Datacraft, 2026
"""Policy service for access control decisions."""
import logging
from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from .db import PolicyDB
from .engine import (
	PolicyEngine, DepartmentIsolationEngine, PolicyContext,
	SubjectAttributes, ResourceAttributes, EnvironmentAttributes, PolicyDecision
)
from papermerge.core.features.departments.db import api as dept_api
from .models import Policy, PolicyEffect

logger = logging.getLogger(__name__)


class PolicyService:
	"""
	High-level service for policy-based access control.

	Usage:
		async with get_session() as session:
			service = PolicyService(session)
			decision = await service.check_access(
				user_id="user-123",
				resource_id="doc-456",
				resource_type="document",
				action="view",
			)
			if not decision.allowed:
				raise PermissionDenied(decision.reason)
	"""

	def __init__(self, session: AsyncSession):
		self.session = session
		self.db = PolicyDB(session)
		self._engine: PolicyEngine | None = None
		self._dept_engine = DepartmentIsolationEngine()
		self._policies_loaded = False

	async def _ensure_policies_loaded(self, tenant_id: str | None = None):
		"""Load active policies into the engine."""
		if not self._policies_loaded or self._engine is None:
			models = await self.db.get_active_policies(tenant_id)
			policies = [self.db.model_to_policy(m) for m in models]
			self._engine = PolicyEngine(policies)
			self._policies_loaded = True
			logger.debug(f"Loaded {len(policies)} active policies")

	def invalidate_cache(self):
		"""Invalidate the policy cache, forcing reload on next access check."""
		self._policies_loaded = False
		self._engine = None

	async def check_access(
		self,
		user_id: str,
		resource_id: str,
		resource_type: str,
		action: str,
		username: str | None = None,
		user_roles: list[str] | None = None,
		user_groups: list[str] | None = None,
		user_department: str | None = None,
		user_department_hierarchy: list[str] | None = None,
		is_superuser: bool = False,
		resource_owner_id: str | None = None,
		resource_department: str | None = None,
		resource_classification: str | None = None,
		resource_tags: list[str] | None = None,
		tenant_id: str | None = None,
		ip_address: str | None = None,
		mfa_verified: bool = False,
		log_decision: bool = True,
		custom_subject_attrs: dict[str, Any] | None = None,
		custom_resource_attrs: dict[str, Any] | None = None,
	) -> PolicyDecision:
		"""
		Check if a user can perform an action on a resource.

		This is the main entry point for policy evaluation.
		"""
		await self._ensure_policies_loaded(tenant_id)

		# 1. Enforce Departmental Sovereignty (Isolation)
		# If resource has a department, user must have access via hierarchy or grant
		if resource_department and not is_superuser:
			can_access_dept = await self.can_access_department(
				user_id=user_id,
				user_department=user_department,
				user_department_hierarchy=user_department_hierarchy,
				target_department=resource_department,
				is_superuser=is_superuser
			)
			if not can_access_dept:
				return PolicyDecision(
					allowed=False,
					effect=PolicyEffect.DENY,
					reason=f"Departmental Sovereignty: Access to department {resource_department} denied",
					evaluation_time_ms=0.0
				)

		# 2. Fetch Department-level permissions (DepartmentAccessRule)
		dept_permissions = {}
		if user_id:
			# Convert user_id to UUID if it's a string
			import uuid
			u_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
			# We assume resource_type might map to document_type_id in some cases
			# For now, we fetch general permissions for the user's departments
			dept_permissions = await dept_api.get_effective_permissions(
				self.session, u_id, document_type_id=None # TODO: Map resource_id to doc_type if applicable
			)

		# 3. Build context
		context = PolicyContext(
			subject=SubjectAttributes(
				id=user_id,
				username=username or "",
				roles=user_roles or [],
				groups=user_groups or [],
				department=user_department,
				department_hierarchy=user_department_hierarchy or [],
				tenant_id=tenant_id,
				is_superuser=is_superuser,
				custom_attributes=custom_subject_attrs or {},
			),
			resource=ResourceAttributes(
				id=resource_id,
				type=resource_type,
				owner_id=resource_owner_id,
				department=resource_department,
				classification=resource_classification,
				tags=resource_tags or [],
				tenant_id=tenant_id,
				custom_attributes=custom_resource_attrs or {},
			),
			action=action,
			environment=EnvironmentAttributes(
				ip_address=ip_address,
				mfa_verified=mfa_verified,
			),
			department_permissions=dept_permissions,
		)

		# Evaluate policies
		assert self._engine is not None
		decision = self._engine.evaluate(context)

		# Log the decision
		if log_decision:
			await self.db.log_evaluation(
				policy_id=decision.matched_policy.id if decision.matched_policy else None,
				subject_id=user_id,
				subject_username=username,
				resource_id=resource_id,
				resource_type=resource_type,
				action=action,
				allowed=decision.allowed,
				effect=decision.effect,
				reason=decision.reason,
				evaluation_time_ms=decision.evaluation_time_ms,
				context_snapshot={
					"subject": {"id": user_id, "roles": user_roles, "groups": user_groups, "department": user_department},
					"resource": {"id": resource_id, "type": resource_type, "owner": resource_owner_id, "department": resource_department},
					"action": action,
				},
				tenant_id=tenant_id,
			)

		return decision

	async def can_access_department(
		self,
		user_id: str,
		user_department: str | None,
		user_department_hierarchy: list[str] | None,
		target_department: str,
		is_superuser: bool = False,
	) -> bool:
		"""Check if a user can access resources in a department."""
		subject = SubjectAttributes(
			id=user_id,
			username="",
			department=user_department,
			department_hierarchy=user_department_hierarchy or [],
			is_superuser=is_superuser,
		)

		# Load cross-department grants
		grants = await self.db.get_user_department_grants(user_id)
		for grant in grants:
			self._dept_engine.grant_cross_department_access(user_id, grant.department_id)

		return self._dept_engine.can_access_department(subject, target_department)

	async def filter_resources_by_department(
		self,
		user_id: str,
		user_department: str | None,
		user_department_hierarchy: list[str] | None,
		resources: list[dict],
		department_key: str = "department",
		is_superuser: bool = False,
	) -> list[dict]:
		"""Filter resources to only those the user can access based on department."""
		if is_superuser:
			return resources

		# Load cross-department grants
		grants = await self.db.get_user_department_grants(user_id)
		for grant in grants:
			self._dept_engine.grant_cross_department_access(user_id, grant.department_id)

		subject = SubjectAttributes(
			id=user_id,
			username="",
			department=user_department,
			department_hierarchy=user_department_hierarchy or [],
			is_superuser=is_superuser,
		)

		return [
			r for r in resources
			if not r.get(department_key) or self._dept_engine.can_access_department(subject, r[department_key])
		]

	async def get_effective_permissions(
		self,
		user_id: str,
		resource_type: str,
		user_roles: list[str] | None = None,
		user_groups: list[str] | None = None,
		tenant_id: str | None = None,
	) -> dict[str, bool]:
		"""
		Get effective permissions for a user on a resource type.

		Returns a dict of action -> allowed for common actions.
		"""
		common_actions = ["view", "edit", "delete", "share", "download", "print", "export"]
		permissions = {}

		for action in common_actions:
			decision = await self.check_access(
				user_id=user_id,
				resource_id="*",  # Wildcard for permission check
				resource_type=resource_type,
				action=action,
				user_roles=user_roles,
				user_groups=user_groups,
				tenant_id=tenant_id,
				log_decision=False,  # Don't log permission checks
			)
			permissions[action] = decision.allowed

		return permissions


class PolicyServiceFactory:
	"""Factory for creating PolicyService instances."""

	@staticmethod
	def create(session: AsyncSession) -> PolicyService:
		"""Create a new PolicyService instance."""
		return PolicyService(session)


# Convenience function for dependency injection
async def get_policy_service(session: AsyncSession) -> PolicyService:
	"""Get a PolicyService instance for the given session."""
	return PolicyService(session)
