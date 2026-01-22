# (c) Copyright Datacraft, 2026
"""Database operations for policy management."""
from datetime import datetime
from typing import Sequence
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7str

from .orm import PolicyModel, PolicyApprovalModel, PolicyEvaluationLogModel, DepartmentAccessModel
from ..models import Policy, PolicyRule, PolicyCondition, PolicyApproval, PolicyEffect, PolicyStatus


class PolicyDB:
	"""Database operations for policies."""

	def __init__(self, session: AsyncSession):
		self.session = session

	# --- Policy CRUD ---

	async def create_policy(self, policy: Policy) -> PolicyModel:
		"""Create a new policy."""
		model = PolicyModel(
			id=policy.id or uuid7str(),
			name=policy.name,
			description=policy.description,
			effect=policy.effect,
			priority=policy.priority,
			rules_json=[r.to_dict() for r in policy.rules],
			actions=policy.actions,
			resource_types=policy.resource_types,
			status=policy.status,
			tenant_id=policy.tenant_id,
			created_by=policy.created_by,
			valid_from=policy.valid_from,
			valid_until=policy.valid_until,
			metadata_json=policy.metadata,
		)
		self.session.add(model)
		await self.session.flush()
		return model

	async def get_policy(self, policy_id: str) -> PolicyModel | None:
		"""Get a policy by ID."""
		return await self.session.get(PolicyModel, policy_id)

	async def get_policies(
		self,
		tenant_id: str | None = None,
		status: PolicyStatus | None = None,
		effect: PolicyEffect | None = None,
		limit: int = 100,
		offset: int = 0,
	) -> Sequence[PolicyModel]:
		"""Get policies with optional filters."""
		query = select(PolicyModel)
		conditions = []

		if tenant_id is not None:
			conditions.append(PolicyModel.tenant_id == tenant_id)
		if status is not None:
			conditions.append(PolicyModel.status == status)
		if effect is not None:
			conditions.append(PolicyModel.effect == effect)

		if conditions:
			query = query.where(and_(*conditions))

		query = query.order_by(PolicyModel.priority, PolicyModel.created_at.desc())
		query = query.limit(limit).offset(offset)

		result = await self.session.execute(query)
		return result.scalars().all()

	async def get_active_policies(self, tenant_id: str | None = None) -> Sequence[PolicyModel]:
		"""Get all active and currently valid policies."""
		now = datetime.utcnow()
		query = select(PolicyModel).where(
			and_(
				PolicyModel.status == PolicyStatus.ACTIVE,
				or_(PolicyModel.valid_from.is_(None), PolicyModel.valid_from <= now),
				or_(PolicyModel.valid_until.is_(None), PolicyModel.valid_until >= now),
			)
		)
		if tenant_id:
			query = query.where(
				or_(PolicyModel.tenant_id.is_(None), PolicyModel.tenant_id == tenant_id)
			)
		query = query.order_by(PolicyModel.priority)
		result = await self.session.execute(query)
		return result.scalars().all()

	async def update_policy(self, policy_id: str, **kwargs) -> PolicyModel | None:
		"""Update a policy."""
		model = await self.get_policy(policy_id)
		if not model:
			return None

		for key, value in kwargs.items():
			if key == "rules" and isinstance(value, list):
				setattr(model, "rules_json", [r.to_dict() if hasattr(r, "to_dict") else r for r in value])
			elif hasattr(model, key):
				setattr(model, key, value)

		model.updated_at = datetime.utcnow()
		await self.session.flush()
		return model

	async def delete_policy(self, policy_id: str) -> bool:
		"""Delete a policy."""
		model = await self.get_policy(policy_id)
		if not model:
			return False
		await self.session.delete(model)
		await self.session.flush()
		return True

	# --- Policy Approval ---

	async def create_approval_request(
		self,
		policy_id: str,
		requested_by: str,
		changes_summary: str | None = None,
	) -> PolicyApprovalModel:
		"""Create a policy approval request."""
		policy = await self.get_policy(policy_id)
		snapshot = self._model_to_dict(policy) if policy else {}

		approval = PolicyApprovalModel(
			id=uuid7str(),
			policy_id=policy_id,
			requested_by=requested_by,
			status="pending",
			policy_snapshot=snapshot,
			changes_summary=changes_summary,
		)
		self.session.add(approval)
		await self.session.flush()
		return approval

	async def get_pending_approvals(self, tenant_id: str | None = None) -> Sequence[PolicyApprovalModel]:
		"""Get pending approval requests."""
		query = select(PolicyApprovalModel).where(PolicyApprovalModel.status == "pending")
		if tenant_id:
			query = query.join(PolicyModel).where(PolicyModel.tenant_id == tenant_id)
		query = query.order_by(PolicyApprovalModel.requested_at.desc())
		result = await self.session.execute(query)
		return result.scalars().all()

	async def approve_policy(
		self,
		approval_id: str,
		reviewer_id: str,
		comments: str | None = None,
	) -> PolicyApprovalModel | None:
		"""Approve a policy change."""
		approval = await self.session.get(PolicyApprovalModel, approval_id)
		if not approval or approval.status != "pending":
			return None

		approval.status = "approved"
		approval.reviewed_by = reviewer_id
		approval.reviewed_at = datetime.utcnow()
		approval.comments = comments

		# Activate the policy
		if approval.policy:
			approval.policy.status = PolicyStatus.ACTIVE
			approval.policy.updated_at = datetime.utcnow()

		await self.session.flush()
		return approval

	async def reject_policy(
		self,
		approval_id: str,
		reviewer_id: str,
		comments: str | None = None,
	) -> PolicyApprovalModel | None:
		"""Reject a policy change."""
		approval = await self.session.get(PolicyApprovalModel, approval_id)
		if not approval or approval.status != "pending":
			return None

		approval.status = "rejected"
		approval.reviewed_by = reviewer_id
		approval.reviewed_at = datetime.utcnow()
		approval.comments = comments

		await self.session.flush()
		return approval

	# --- Evaluation Logging ---

	async def log_evaluation(
		self,
		policy_id: str | None,
		subject_id: str,
		subject_username: str | None,
		resource_id: str,
		resource_type: str,
		action: str,
		allowed: bool,
		effect: PolicyEffect,
		reason: str,
		evaluation_time_ms: float,
		context_snapshot: dict,
		tenant_id: str | None = None,
	) -> PolicyEvaluationLogModel:
		"""Log a policy evaluation decision."""
		log = PolicyEvaluationLogModel(
			id=uuid7str(),
			policy_id=policy_id,
			subject_id=subject_id,
			subject_username=subject_username,
			resource_id=resource_id,
			resource_type=resource_type,
			action=action,
			allowed=allowed,
			effect=effect,
			reason=reason,
			evaluation_time_ms=int(evaluation_time_ms),
			context_snapshot=context_snapshot,
			tenant_id=tenant_id,
		)
		self.session.add(log)
		await self.session.flush()
		return log

	async def get_evaluation_logs(
		self,
		tenant_id: str | None = None,
		subject_id: str | None = None,
		resource_id: str | None = None,
		action: str | None = None,
		since: datetime | None = None,
		limit: int = 100,
	) -> Sequence[PolicyEvaluationLogModel]:
		"""Query evaluation logs."""
		query = select(PolicyEvaluationLogModel)
		conditions = []

		if tenant_id:
			conditions.append(PolicyEvaluationLogModel.tenant_id == tenant_id)
		if subject_id:
			conditions.append(PolicyEvaluationLogModel.subject_id == subject_id)
		if resource_id:
			conditions.append(PolicyEvaluationLogModel.resource_id == resource_id)
		if action:
			conditions.append(PolicyEvaluationLogModel.action == action)
		if since:
			conditions.append(PolicyEvaluationLogModel.timestamp >= since)

		if conditions:
			query = query.where(and_(*conditions))

		query = query.order_by(PolicyEvaluationLogModel.timestamp.desc()).limit(limit)
		result = await self.session.execute(query)
		return result.scalars().all()

	# --- Department Access ---

	async def grant_department_access(
		self,
		user_id: str,
		department_id: str,
		granted_by: str,
		expires_at: datetime | None = None,
		reason: str | None = None,
		tenant_id: str | None = None,
	) -> DepartmentAccessModel:
		"""Grant cross-department access."""
		grant = DepartmentAccessModel(
			id=uuid7str(),
			user_id=user_id,
			department_id=department_id,
			granted_by=granted_by,
			expires_at=expires_at,
			reason=reason,
			tenant_id=tenant_id,
		)
		self.session.add(grant)
		await self.session.flush()
		return grant

	async def revoke_department_access(self, user_id: str, department_id: str) -> bool:
		"""Revoke cross-department access."""
		query = select(DepartmentAccessModel).where(
			and_(
				DepartmentAccessModel.user_id == user_id,
				DepartmentAccessModel.department_id == department_id,
			)
		)
		result = await self.session.execute(query)
		grant = result.scalar_one_or_none()
		if grant:
			await self.session.delete(grant)
			await self.session.flush()
			return True
		return False

	async def get_user_department_grants(self, user_id: str) -> Sequence[DepartmentAccessModel]:
		"""Get all department access grants for a user."""
		now = datetime.utcnow()
		query = select(DepartmentAccessModel).where(
			and_(
				DepartmentAccessModel.user_id == user_id,
				or_(
					DepartmentAccessModel.expires_at.is_(None),
					DepartmentAccessModel.expires_at > now,
				),
			)
		)
		result = await self.session.execute(query)
		return result.scalars().all()

	# --- Helpers ---

	def _model_to_dict(self, model: PolicyModel) -> dict:
		"""Convert PolicyModel to dict for snapshots."""
		return {
			"id": model.id,
			"name": model.name,
			"description": model.description,
			"effect": model.effect.value if model.effect else None,
			"priority": model.priority,
			"rules_json": model.rules_json,
			"actions": model.actions,
			"resource_types": model.resource_types,
			"status": model.status.value if model.status else None,
		}

	def model_to_policy(self, model: PolicyModel) -> Policy:
		"""Convert PolicyModel to domain Policy object."""
		return Policy(
			id=model.id,
			name=model.name,
			description=model.description or "",
			effect=model.effect,
			priority=model.priority,
			rules=[PolicyRule.from_dict(r) for r in (model.rules_json or [])],
			actions=model.actions or [],
			resource_types=model.resource_types or [],
			status=model.status,
			tenant_id=model.tenant_id,
			created_by=model.created_by,
			created_at=model.created_at,
			updated_at=model.updated_at,
			valid_from=model.valid_from,
			valid_until=model.valid_until,
			metadata=model.metadata_json or {},
		)
