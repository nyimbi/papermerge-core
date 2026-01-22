# (c) Copyright Datacraft, 2026
"""FastAPI router for policy management."""
from datetime import datetime, timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7str

from papermerge.core.db.engine import get_session
from papermerge.core.auth import get_current_user
from papermerge.core.features.users.db.orm import User

from .db import PolicyDB, PolicyEvaluationLogModel
from .models import Policy, PolicyRule, PolicyCondition, PolicyEffect, PolicyStatus
from .engine import PolicyEngine, PolicyContext, SubjectAttributes, ResourceAttributes, EnvironmentAttributes
from .parser import PolicyParser, PolicySyntaxError
from .views import (
	PolicyCreate, PolicyCreateFromDSL, PolicyUpdate, PolicyResponse, PolicyListResponse,
	ApprovalRequestCreate, ApprovalAction, ApprovalResponse,
	EvaluationLogResponse, EvaluateRequest, EvaluateResponse,
	DepartmentAccessGrant, DepartmentAccessResponse, PolicyAnalytics,
	PolicyRuleSchema, PolicyConditionSchema,
)

router = APIRouter(prefix="/policies", tags=["policies"])


# --- Policy CRUD ---

@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
	data: PolicyCreate,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Create a new policy."""
	db = PolicyDB(session)

	policy = Policy(
		id=uuid7str(),
		name=data.name,
		description=data.description,
		effect=data.effect,
		priority=data.priority,
		rules=[PolicyRule.from_dict(r.model_dump()) for r in data.rules],
		actions=data.actions,
		resource_types=data.resource_types,
		status=PolicyStatus.DRAFT,
		tenant_id=current_user.tenant_id,
		created_by=current_user.id,
		valid_from=data.valid_from,
		valid_until=data.valid_until,
		metadata=data.metadata,
	)

	model = await db.create_policy(policy)
	await session.commit()
	return _model_to_response(model)


@router.post("/from-dsl", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy_from_dsl(
	data: PolicyCreateFromDSL,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Create a policy from DSL text."""
	parser = PolicyParser()

	try:
		policy = parser.parse(data.dsl_text, policy_id=uuid7str(), name=data.name)
	except PolicySyntaxError as e:
		raise HTTPException(status_code=400, detail=f"Invalid policy DSL: {e}")

	policy.description = data.description
	policy.priority = data.priority
	policy.tenant_id = current_user.tenant_id
	policy.created_by = current_user.id
	policy.valid_from = data.valid_from
	policy.valid_until = data.valid_until

	db = PolicyDB(session)
	model = await db.create_policy(policy)
	model.dsl_text = data.dsl_text
	await session.commit()
	return _model_to_response(model)


@router.get("", response_model=PolicyListResponse)
async def list_policies(
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
	status_filter: PolicyStatus | None = Query(None, alias="status"),
	effect_filter: PolicyEffect | None = Query(None, alias="effect"),
	limit: int = Query(50, ge=1, le=200),
	offset: int = Query(0, ge=0),
):
	"""List policies with optional filters."""
	db = PolicyDB(session)
	policies = await db.get_policies(
		tenant_id=current_user.tenant_id,
		status=status_filter,
		effect=effect_filter,
		limit=limit,
		offset=offset,
	)
	return PolicyListResponse(
		items=[_model_to_response(p) for p in policies],
		total=len(policies),
		limit=limit,
		offset=offset,
	)


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
	policy_id: str,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Get a policy by ID."""
	db = PolicyDB(session)
	model = await db.get_policy(policy_id)
	if not model:
		raise HTTPException(status_code=404, detail="Policy not found")
	if model.tenant_id and model.tenant_id != current_user.tenant_id:
		raise HTTPException(status_code=403, detail="Access denied")
	return _model_to_response(model)


@router.patch("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
	policy_id: str,
	data: PolicyUpdate,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Update a policy."""
	db = PolicyDB(session)
	model = await db.get_policy(policy_id)
	if not model:
		raise HTTPException(status_code=404, detail="Policy not found")
	if model.tenant_id and model.tenant_id != current_user.tenant_id:
		raise HTTPException(status_code=403, detail="Access denied")

	update_data = data.model_dump(exclude_unset=True)
	if "rules" in update_data:
		update_data["rules_json"] = [r.model_dump() if hasattr(r, "model_dump") else r for r in update_data.pop("rules")]
	if "metadata" in update_data:
		update_data["metadata_json"] = update_data.pop("metadata")

	model = await db.update_policy(policy_id, **update_data)
	await session.commit()
	return _model_to_response(model)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
	policy_id: str,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Delete a policy."""
	db = PolicyDB(session)
	model = await db.get_policy(policy_id)
	if not model:
		raise HTTPException(status_code=404, detail="Policy not found")
	if model.tenant_id and model.tenant_id != current_user.tenant_id:
		raise HTTPException(status_code=403, detail="Access denied")

	await db.delete_policy(policy_id)
	await session.commit()


# --- Policy Evaluation ---

@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate_policy(
	data: EvaluateRequest,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Evaluate policies against a request context."""
	db = PolicyDB(session)

	# Load active policies
	policy_models = await db.get_active_policies(tenant_id=current_user.tenant_id)
	policies = [db.model_to_policy(m) for m in policy_models]

	# Build context
	context = PolicyContext(
		subject=SubjectAttributes(
			id=data.subject_id,
			username=data.subject_username or "",
			roles=data.subject_roles,
			groups=data.subject_groups,
			department=data.subject_department,
			tenant_id=current_user.tenant_id,
		),
		resource=ResourceAttributes(
			id=data.resource_id,
			type=data.resource_type,
			owner_id=data.resource_owner_id,
			department=data.resource_department,
			classification=data.resource_classification,
			tenant_id=current_user.tenant_id,
		),
		action=data.action,
		environment=EnvironmentAttributes(
			ip_address=data.ip_address,
			mfa_verified=data.mfa_verified,
		),
	)

	# Evaluate
	engine = PolicyEngine(policies)
	decision = engine.evaluate(context)

	# Log evaluation
	await db.log_evaluation(
		policy_id=decision.matched_policy.id if decision.matched_policy else None,
		subject_id=data.subject_id,
		subject_username=data.subject_username,
		resource_id=data.resource_id,
		resource_type=data.resource_type,
		action=data.action,
		allowed=decision.allowed,
		effect=decision.effect,
		reason=decision.reason,
		evaluation_time_ms=decision.evaluation_time_ms,
		context_snapshot=data.model_dump(),
		tenant_id=current_user.tenant_id,
	)
	await session.commit()

	return EvaluateResponse(
		allowed=decision.allowed,
		effect=decision.effect,
		matched_policy_id=decision.matched_policy.id if decision.matched_policy else None,
		matched_policy_name=decision.matched_policy.name if decision.matched_policy else None,
		reason=decision.reason,
		evaluation_time_ms=decision.evaluation_time_ms,
	)


# --- Approval Workflow ---

@router.post("/{policy_id}/submit-for-approval", response_model=ApprovalResponse)
async def submit_for_approval(
	policy_id: str,
	data: ApprovalRequestCreate,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Submit a policy for approval."""
	db = PolicyDB(session)
	model = await db.get_policy(policy_id)
	if not model:
		raise HTTPException(status_code=404, detail="Policy not found")

	model.status = PolicyStatus.PENDING_APPROVAL
	approval = await db.create_approval_request(
		policy_id=policy_id,
		requested_by=current_user.id,
		changes_summary=data.changes_summary,
	)
	await session.commit()

	return ApprovalResponse(
		id=approval.id,
		policy_id=approval.policy_id,
		requested_by=approval.requested_by,
		requested_at=approval.requested_at,
		status=approval.status,
		changes_summary=approval.changes_summary,
		policy_name=model.name,
	)


@router.get("/approvals/pending", response_model=list[ApprovalResponse])
async def list_pending_approvals(
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""List pending approval requests."""
	db = PolicyDB(session)
	approvals = await db.get_pending_approvals(tenant_id=current_user.tenant_id)
	return [
		ApprovalResponse(
			id=a.id,
			policy_id=a.policy_id,
			requested_by=a.requested_by,
			requested_at=a.requested_at,
			status=a.status,
			reviewed_by=a.reviewed_by,
			reviewed_at=a.reviewed_at,
			comments=a.comments,
			changes_summary=a.changes_summary,
			policy_name=a.policy.name if a.policy else None,
		)
		for a in approvals
	]


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_policy_change(
	approval_id: str,
	data: ApprovalAction,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Approve a policy change."""
	db = PolicyDB(session)
	approval = await db.approve_policy(approval_id, current_user.id, data.comments)
	if not approval:
		raise HTTPException(status_code=404, detail="Approval request not found or already processed")
	await session.commit()

	return ApprovalResponse(
		id=approval.id,
		policy_id=approval.policy_id,
		requested_by=approval.requested_by,
		requested_at=approval.requested_at,
		status=approval.status,
		reviewed_by=approval.reviewed_by,
		reviewed_at=approval.reviewed_at,
		comments=approval.comments,
		changes_summary=approval.changes_summary,
		policy_name=approval.policy.name if approval.policy else None,
	)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_policy_change(
	approval_id: str,
	data: ApprovalAction,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Reject a policy change."""
	db = PolicyDB(session)
	approval = await db.reject_policy(approval_id, current_user.id, data.comments)
	if not approval:
		raise HTTPException(status_code=404, detail="Approval request not found or already processed")

	# Revert to draft
	if approval.policy:
		approval.policy.status = PolicyStatus.DRAFT

	await session.commit()

	return ApprovalResponse(
		id=approval.id,
		policy_id=approval.policy_id,
		requested_by=approval.requested_by,
		requested_at=approval.requested_at,
		status=approval.status,
		reviewed_by=approval.reviewed_by,
		reviewed_at=approval.reviewed_at,
		comments=approval.comments,
		changes_summary=approval.changes_summary,
		policy_name=approval.policy.name if approval.policy else None,
	)


# --- Evaluation Logs ---

@router.get("/logs", response_model=list[EvaluationLogResponse])
async def get_evaluation_logs(
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
	subject_id: str | None = None,
	resource_id: str | None = None,
	action: str | None = None,
	hours: int = Query(24, ge=1, le=720),
	limit: int = Query(100, ge=1, le=1000),
):
	"""Get policy evaluation logs."""
	db = PolicyDB(session)
	since = datetime.utcnow() - timedelta(hours=hours)
	logs = await db.get_evaluation_logs(
		tenant_id=current_user.tenant_id,
		subject_id=subject_id,
		resource_id=resource_id,
		action=action,
		since=since,
		limit=limit,
	)
	return [EvaluationLogResponse.model_validate(log) for log in logs]


# --- Department Access ---

@router.post("/department-access", response_model=DepartmentAccessResponse, status_code=status.HTTP_201_CREATED)
async def grant_department_access(
	data: DepartmentAccessGrant,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Grant cross-department access to a user."""
	db = PolicyDB(session)
	grant = await db.grant_department_access(
		user_id=data.user_id,
		department_id=data.department_id,
		granted_by=current_user.id,
		expires_at=data.expires_at,
		reason=data.reason,
		tenant_id=current_user.tenant_id,
	)
	await session.commit()
	return DepartmentAccessResponse.model_validate(grant)


@router.delete("/department-access/{user_id}/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_department_access(
	user_id: str,
	department_id: str,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Revoke cross-department access."""
	db = PolicyDB(session)
	revoked = await db.revoke_department_access(user_id, department_id)
	if not revoked:
		raise HTTPException(status_code=404, detail="Access grant not found")
	await session.commit()


@router.get("/department-access/{user_id}", response_model=list[DepartmentAccessResponse])
async def get_user_department_access(
	user_id: str,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Get a user's department access grants."""
	db = PolicyDB(session)
	grants = await db.get_user_department_grants(user_id)
	return [DepartmentAccessResponse.model_validate(g) for g in grants]


# --- Analytics ---

@router.get("/analytics", response_model=PolicyAnalytics)
async def get_policy_analytics(
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Get policy analytics and statistics."""
	from .db.orm import PolicyModel

	db = PolicyDB(session)
	today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

	# Count policies
	total_query = select(func.count()).select_from(PolicyModel).where(
		PolicyModel.tenant_id == current_user.tenant_id
	)
	total_result = await session.execute(total_query)
	total_policies = total_result.scalar() or 0

	active_query = select(func.count()).select_from(PolicyModel).where(
		and_(PolicyModel.tenant_id == current_user.tenant_id, PolicyModel.status == PolicyStatus.ACTIVE)
	)
	active_result = await session.execute(active_query)
	active_policies = active_result.scalar() or 0

	# Count pending approvals
	from .db.orm import PolicyApprovalModel
	pending_query = select(func.count()).select_from(PolicyApprovalModel).where(
		PolicyApprovalModel.status == "pending"
	)
	pending_result = await session.execute(pending_query)
	pending_approvals = pending_result.scalar() or 0

	# Today's evaluations
	eval_today_query = select(func.count()).select_from(PolicyEvaluationLogModel).where(
		and_(
			PolicyEvaluationLogModel.tenant_id == current_user.tenant_id,
			PolicyEvaluationLogModel.timestamp >= today,
		)
	)
	eval_result = await session.execute(eval_today_query)
	evaluations_today = eval_result.scalar() or 0

	# Allow/Deny rates
	allow_query = select(func.count()).select_from(PolicyEvaluationLogModel).where(
		and_(
			PolicyEvaluationLogModel.tenant_id == current_user.tenant_id,
			PolicyEvaluationLogModel.timestamp >= today,
			PolicyEvaluationLogModel.allowed == True,
		)
	)
	allow_result = await session.execute(allow_query)
	allow_count = allow_result.scalar() or 0

	allow_rate = (allow_count / evaluations_today * 100) if evaluations_today > 0 else 0.0
	deny_rate = 100.0 - allow_rate if evaluations_today > 0 else 0.0

	# Top denied actions
	denied_query = (
		select(PolicyEvaluationLogModel.action, func.count().label("count"))
		.where(
			and_(
				PolicyEvaluationLogModel.tenant_id == current_user.tenant_id,
				PolicyEvaluationLogModel.timestamp >= today,
				PolicyEvaluationLogModel.allowed == False,
			)
		)
		.group_by(PolicyEvaluationLogModel.action)
		.order_by(func.count().desc())
		.limit(5)
	)
	denied_result = await session.execute(denied_query)
	top_denied = [{"action": row[0], "count": row[1]} for row in denied_result]

	# Average latency
	latency_query = select(func.avg(PolicyEvaluationLogModel.evaluation_time_ms)).where(
		and_(
			PolicyEvaluationLogModel.tenant_id == current_user.tenant_id,
			PolicyEvaluationLogModel.timestamp >= today,
		)
	)
	latency_result = await session.execute(latency_query)
	avg_latency = latency_result.scalar() or 0.0

	return PolicyAnalytics(
		total_policies=total_policies,
		active_policies=active_policies,
		pending_approvals=pending_approvals,
		evaluations_today=evaluations_today,
		allow_rate=round(allow_rate, 2),
		deny_rate=round(deny_rate, 2),
		top_denied_actions=top_denied,
		evaluation_latency_avg_ms=round(float(avg_latency), 2),
	)


# --- DSL Conversion ---

@router.post("/convert-to-dsl", response_model=dict)
async def convert_policy_to_dsl(
	policy_id: str,
	session: Annotated[AsyncSession, Depends(get_session)],
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Convert a policy to DSL text."""
	db = PolicyDB(session)
	model = await db.get_policy(policy_id)
	if not model:
		raise HTTPException(status_code=404, detail="Policy not found")

	policy = db.model_to_policy(model)
	dsl_text = PolicyParser.to_dsl(policy)
	return {"dsl": dsl_text}


@router.post("/validate-dsl", response_model=dict)
async def validate_dsl(
	dsl_text: str,
	current_user: Annotated[User, Depends(get_current_user)],
):
	"""Validate policy DSL syntax."""
	parser = PolicyParser()
	try:
		policy = parser.parse(dsl_text, policy_id="validation", name="Validation")
		return {
			"valid": True,
			"effect": policy.effect.value,
			"actions": policy.actions,
			"resource_types": policy.resource_types,
			"rule_count": len(policy.rules),
		}
	except PolicySyntaxError as e:
		return {"valid": False, "error": str(e)}


# --- Helpers ---

def _model_to_response(model) -> PolicyResponse:
	"""Convert ORM model to response schema."""
	rules = []
	for r in (model.rules_json or []):
		rules.append(PolicyRuleSchema(
			conditions=[
				PolicyConditionSchema(**c) for c in r.get("conditions", [])
			],
			logic=r.get("logic", "AND"),
		))

	return PolicyResponse(
		id=model.id,
		name=model.name,
		description=model.description or "",
		effect=model.effect,
		priority=model.priority,
		rules=rules,
		actions=model.actions or [],
		resource_types=model.resource_types or [],
		status=model.status,
		tenant_id=model.tenant_id,
		created_by=model.created_by,
		created_at=model.created_at,
		updated_at=model.updated_at,
		valid_from=model.valid_from,
		valid_until=model.valid_until,
		dsl_text=model.dsl_text,
	)
