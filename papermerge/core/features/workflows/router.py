# (c) Copyright Datacraft, 2026
"""Workflow management API endpoints with Prefect integration."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.config.features import is_feature_enabled
from .prefect_engine import PrefectWorkflowEngine
from . import schema

router = APIRouter(
	prefix="/workflows",
	tags=["workflows"],
)

logger = logging.getLogger(__name__)


def get_workflow_engine(db: AsyncSession = Depends(get_db)) -> PrefectWorkflowEngine:
	"""Get workflow engine instance."""
	return PrefectWorkflowEngine(db)


@router.get("/")
async def list_workflows(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 20,
) -> schema.WorkflowListResponse:
	"""List available workflows."""
	from sqlalchemy import select, func
	from .db.orm import Workflow

	offset = (page - 1) * page_size

	# Get total count
	count_stmt = select(func.count()).select_from(Workflow).where(
		Workflow.is_active == True
	)
	total = await db_session.scalar(count_stmt)

	# Get workflows
	stmt = select(Workflow).where(
		Workflow.is_active == True
	).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	workflows = result.scalars().all()

	return schema.WorkflowListResponse(
		items=[schema.WorkflowInfo.model_validate(w) for w in workflows],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get("/executions/")
async def list_executions(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	workflow_id: str | None = None,
	status: str | None = None,
	page: int = 1,
	page_size: int = 20,
) -> schema.WorkflowExecutionListResponse:
	"""List workflow executions (instances)."""
	from sqlalchemy import select, func
	from sqlalchemy.orm import selectinload
	from .db.orm import WorkflowInstance, Workflow

	offset = (page - 1) * page_size

	# Base query
	base_query = select(WorkflowInstance).options(
		selectinload(WorkflowInstance.workflow)
	)

	# Apply filters
	if workflow_id:
		try:
			from uuid import UUID as UUIDType
			wf_uuid = UUIDType(workflow_id)
			base_query = base_query.where(WorkflowInstance.workflow_id == wf_uuid)
		except ValueError:
			pass
	if status:
		base_query = base_query.where(WorkflowInstance.status == status)

	# Get total count
	count_query = select(func.count()).select_from(WorkflowInstance)
	if workflow_id:
		try:
			from uuid import UUID as UUIDType
			wf_uuid = UUIDType(workflow_id)
			count_query = count_query.where(WorkflowInstance.workflow_id == wf_uuid)
		except ValueError:
			pass
	if status:
		count_query = count_query.where(WorkflowInstance.status == status)

	total = await db_session.scalar(count_query)

	# Get executions with pagination
	stmt = base_query.order_by(WorkflowInstance.started_at.desc()).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	instances = result.scalars().all()

	# Build response
	items = []
	for inst in instances:
		items.append(schema.WorkflowExecution(
			id=inst.id,
			workflow_id=inst.workflow_id,
			workflow_name=inst.workflow.name if inst.workflow else None,
			document_id=inst.document_id,
			status=inst.status,
			current_step_id=inst.current_step_id,
			started_at=inst.started_at,
			completed_at=inst.completed_at,
			initiated_by=inst.initiated_by,
			prefect_flow_run_id=inst.prefect_flow_run_id,
		))

	return schema.WorkflowExecutionListResponse(
		items=items,
		total=total or 0,
		page=page,
		page_size=page_size,
	)


@router.post("/")
async def create_workflow(
	workflow: schema.WorkflowCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.WorkflowInfo:
	"""Create a new workflow definition."""
	from .db.orm import Workflow, WorkflowStep

	db_workflow = Workflow(
		tenant_id=user.tenant_id,
		name=workflow.name,
		description=workflow.description,
		is_active=True,
		created_by=user.id,
		updated_by=user.id,
	)
	db_session.add(db_workflow)
	await db_session.flush()

	# Add steps
	for idx, step_data in enumerate(workflow.steps):
		step = WorkflowStep(
			workflow_id=db_workflow.id,
			name=step_data.name,
			step_order=idx,
			assignee_type=step_data.assignee_type,
			assignee_id=step_data.assignee_id,
			deadline_hours=step_data.deadline_hours,
		)
		db_session.add(step)

	await db_session.commit()
	await db_session.refresh(db_workflow)

	return schema.WorkflowInfo.model_validate(db_workflow)


@router.get("/{workflow_id}")
async def get_workflow(
	workflow_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.WorkflowDetail:
	"""Get workflow details with steps."""
	from .db.orm import Workflow

	workflow = await db_session.get(Workflow, workflow_id)
	if not workflow:
		raise HTTPException(status_code=404, detail="Workflow not found")

	return schema.WorkflowDetail.model_validate(workflow)


@router.post("/{workflow_id}/start")
async def start_workflow(
	workflow_id: UUID,
	request: schema.WorkflowStartRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	engine: PrefectWorkflowEngine = Depends(get_workflow_engine),
) -> schema.WorkflowInstanceInfo:
	"""Start a workflow for a document via Prefect."""
	try:
		instance = await engine.start_workflow(
			workflow_id=workflow_id,
			document_id=request.document_id,
			initiated_by=user.id,
			context=request.context,
		)
		return schema.WorkflowInstanceInfo.model_validate(instance)
	except ValueError as e:
		raise HTTPException(status_code=400, detail=str(e))


@router.get("/instances/pending")
async def get_pending_tasks(
	user: require_scopes(scopes.NODE_VIEW),
	engine: PrefectWorkflowEngine = Depends(get_workflow_engine),
) -> schema.PendingTasksResponse:
	"""Get pending workflow tasks for current user."""
	tasks = await engine.get_pending_tasks(user.id)

	return schema.PendingTasksResponse(
		tasks=[schema.PendingTask.model_validate(t) for t in tasks]
	)


@router.get("/tasks/assigned")
async def get_assigned_tasks(
	user: require_scopes(scopes.NODE_VIEW),
	status: str | None = None,
	limit: int | None = None,
) -> list:
	"""Get workflow tasks assigned to current user.

	Used by the home page to display pending tasks.
	"""
	# Return empty list for now - can be expanded to fetch actual assigned tasks
	return []


@router.post("/instances/{instance_id}/actions")
async def process_workflow_action(
	instance_id: UUID,
	action: schema.WorkflowActionRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	engine: PrefectWorkflowEngine = Depends(get_workflow_engine),
) -> schema.WorkflowInstanceInfo:
	"""Process an action on a workflow step via Prefect."""
	try:
		instance = await engine.process_step_action(
			execution_id=action.execution_id,
			action=action.action,
			user_id=user.id,
			comments=action.comments,
		)
		return schema.WorkflowInstanceInfo.model_validate(instance)
	except ValueError as e:
		raise HTTPException(status_code=400, detail=str(e))


@router.post("/instances/{instance_id}/cancel")
async def cancel_workflow(
	instance_id: UUID,
	request: schema.WorkflowCancelRequest,
	user: require_scopes(scopes.NODE_DELETE),
	engine: PrefectWorkflowEngine = Depends(get_workflow_engine),
) -> schema.WorkflowInstanceInfo:
	"""Cancel a running workflow via Prefect."""
	try:
		instance = await engine.cancel_workflow(
			instance_id=instance_id,
			user_id=user.id,
			reason=request.reason,
		)
		return schema.WorkflowInstanceInfo.model_validate(instance)
	except ValueError as e:
		raise HTTPException(status_code=400, detail=str(e))


@router.post("/instances/{instance_id}/resume")
async def resume_workflow(
	instance_id: UUID,
	data: schema.ApprovalActionRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	engine: PrefectWorkflowEngine = Depends(get_workflow_engine),
) -> schema.WorkflowInstanceInfo:
	"""Resume a paused workflow with approval/input data."""
	try:
		instance = await engine.resume_workflow(
			instance_id=instance_id,
			input_data={
				"decision": data.decision,
				"notes": data.notes or "",
				"reviewer_id": str(user.id),
			},
		)
		return schema.WorkflowInstanceInfo.model_validate(instance)
	except ValueError as e:
		raise HTTPException(status_code=400, detail=str(e))


@router.get("/instances/{instance_id}/status")
async def get_workflow_status(
	instance_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	engine: PrefectWorkflowEngine = Depends(get_workflow_engine),
) -> schema.WorkflowStatusResponse:
	"""Get workflow instance status including Prefect state."""
	try:
		status = await engine.get_instance_status(instance_id)
		return schema.WorkflowStatusResponse(**status)
	except ValueError as e:
		raise HTTPException(status_code=404, detail=str(e))


# ============================================================================
# SLA Monitoring Endpoints
# ============================================================================

@router.post("/approval-requests/{request_id}/delegate")
async def delegate_approval_request(
	request_id: UUID,
	delegation: schema.DelegationRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Delegate an approval request to another user."""
	from .db.orm import WorkflowApprovalRequest
	from papermerge.core.utils.tz import utc_now

	approval_request = await db_session.get(WorkflowApprovalRequest, request_id)
	if not approval_request:
		raise HTTPException(status_code=404, detail="Approval request not found")

	if approval_request.status != "pending":
		raise HTTPException(status_code=400, detail="Only pending requests can be delegated")

	# Check if user is the current assignee
	if approval_request.assignee_id != user.id:
		raise HTTPException(status_code=403, detail="Only the current assignee can delegate")

	# Perform delegation
	approval_request.delegated_from_id = user.id
	approval_request.assignee_id = delegation.delegate_to_id
	approval_request.delegated_at = utc_now()
	approval_request.delegation_reason = delegation.reason

	await db_session.commit()

	return {"status": "delegated", "delegated_to": str(delegation.delegate_to_id)}


@router.get("/sla/dashboard")
async def get_sla_dashboard(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	period_days: int = 30,
) -> schema.SLADashboardResponse:
	"""Get SLA dashboard with compliance statistics and recent alerts."""
	from sqlalchemy import select, func, and_
	from datetime import timedelta
	from .db.orm import WorkflowTaskMetric, WorkflowSLAAlert, SLAStatus
	from papermerge.core.utils.tz import utc_now

	cutoff = utc_now() - timedelta(days=period_days)

	# Get metrics counts by status
	status_counts = await db_session.execute(
		select(
			WorkflowTaskMetric.sla_status,
			func.count(WorkflowTaskMetric.id).label("count"),
		).where(
			and_(
				WorkflowTaskMetric.tenant_id == user.tenant_id,
				WorkflowTaskMetric.created_at >= cutoff,
			)
		).group_by(WorkflowTaskMetric.sla_status)
	)

	counts = {row.sla_status: row.count for row in status_counts}
	total = sum(counts.values())

	stats = schema.SLADashboardStats(
		total_tasks=total,
		on_track=counts.get(SLAStatus.ON_TRACK.value, 0),
		warning=counts.get(SLAStatus.WARNING.value, 0),
		breached=counts.get(SLAStatus.BREACHED.value, 0),
		compliance_rate=(
			counts.get(SLAStatus.ON_TRACK.value, 0) / total * 100
			if total > 0 else 100.0
		),
		period_days=period_days,
	)

	# Get recent unacknowledged alerts
	alerts_result = await db_session.execute(
		select(WorkflowSLAAlert).where(
			and_(
				WorkflowSLAAlert.tenant_id == user.tenant_id,
				WorkflowSLAAlert.acknowledged == False,
			)
		).order_by(WorkflowSLAAlert.created_at.desc()).limit(10)
	)
	recent_alerts = [
		schema.SLAAlertInfo.model_validate(a)
		for a in alerts_result.scalars().all()
	]

	# Get recent metrics
	metrics_result = await db_session.execute(
		select(WorkflowTaskMetric).where(
			WorkflowTaskMetric.tenant_id == user.tenant_id
		).order_by(WorkflowTaskMetric.created_at.desc()).limit(10)
	)
	recent_metrics = [
		schema.TaskMetricInfo.model_validate(m)
		for m in metrics_result.scalars().all()
	]

	return schema.SLADashboardResponse(
		stats=stats,
		recent_alerts=recent_alerts,
		recent_metrics=recent_metrics,
	)


@router.get("/sla/metrics")
async def get_sla_metrics(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	workflow_id: UUID | None = None,
	sla_status: str | None = None,
	page: int = 1,
	page_size: int = 20,
) -> schema.SLAMetricsResponse:
	"""Get paginated SLA metrics."""
	from sqlalchemy import select, func, and_
	from .db.orm import WorkflowTaskMetric

	offset = (page - 1) * page_size

	# Build query
	conditions = [WorkflowTaskMetric.tenant_id == user.tenant_id]
	if workflow_id:
		conditions.append(WorkflowTaskMetric.workflow_id == workflow_id)
	if sla_status:
		conditions.append(WorkflowTaskMetric.sla_status == sla_status)

	# Get total count
	count_stmt = select(func.count()).select_from(WorkflowTaskMetric).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	# Get metrics
	stmt = select(WorkflowTaskMetric).where(
		and_(*conditions)
	).order_by(WorkflowTaskMetric.created_at.desc()).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	metrics = result.scalars().all()

	return schema.SLAMetricsResponse(
		items=[schema.TaskMetricInfo.model_validate(m) for m in metrics],
		total=total or 0,
		page=page,
		page_size=page_size,
	)


@router.post("/sla/alerts/{alert_id}/acknowledge")
async def acknowledge_sla_alert(
	alert_id: UUID,
	request: schema.SLAAlertAcknowledgeRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SLAAlertInfo:
	"""Acknowledge an SLA alert."""
	from .db.orm import WorkflowSLAAlert
	from papermerge.core.utils.tz import utc_now

	alert = await db_session.get(WorkflowSLAAlert, alert_id)
	if not alert:
		raise HTTPException(status_code=404, detail="Alert not found")

	if alert.tenant_id != user.tenant_id:
		raise HTTPException(status_code=403, detail="Access denied")

	alert.acknowledged = True
	alert.acknowledged_by = user.id
	alert.acknowledged_at = utc_now()

	await db_session.commit()
	await db_session.refresh(alert)

	return schema.SLAAlertInfo.model_validate(alert)


@router.get("/sla/configs")
async def list_sla_configs(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	workflow_id: UUID | None = None,
) -> list[schema.SLAConfigInfo]:
	"""List SLA configurations."""
	from sqlalchemy import select, and_
	from .db.orm import WorkflowTaskSLAConfig

	conditions = [
		WorkflowTaskSLAConfig.tenant_id == user.tenant_id,
		WorkflowTaskSLAConfig.is_active == True,
	]
	if workflow_id:
		conditions.append(WorkflowTaskSLAConfig.workflow_id == workflow_id)

	result = await db_session.execute(
		select(WorkflowTaskSLAConfig).where(and_(*conditions))
	)
	configs = result.scalars().all()

	return [schema.SLAConfigInfo.model_validate(c) for c in configs]


@router.post("/sla/configs")
async def create_sla_config(
	config: schema.SLAConfigCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SLAConfigInfo:
	"""Create a new SLA configuration."""
	from .db.orm import WorkflowTaskSLAConfig

	db_config = WorkflowTaskSLAConfig(
		tenant_id=user.tenant_id,
		name=config.name,
		workflow_id=config.workflow_id,
		step_id=config.step_id,
		target_hours=config.target_hours,
		warning_threshold_percent=config.warning_threshold_percent,
		critical_threshold_percent=config.critical_threshold_percent,
		reminder_enabled=config.reminder_enabled,
		reminder_thresholds=config.reminder_thresholds,
		escalation_chain_id=config.escalation_chain_id,
		is_active=True,
	)
	db_session.add(db_config)
	await db_session.commit()
	await db_session.refresh(db_config)

	return schema.SLAConfigInfo.model_validate(db_config)


@router.get("/sla/alerts")
async def list_sla_alerts(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	acknowledged: bool | None = None,
	severity: str | None = None,
	page: int = 1,
	page_size: int = 20,
) -> schema.SLAAlertsResponse:
	"""List SLA alerts with filtering."""
	from sqlalchemy import select, func, and_
	from .db.orm import WorkflowSLAAlert

	offset = (page - 1) * page_size

	conditions = [WorkflowSLAAlert.tenant_id == user.tenant_id]
	if acknowledged is not None:
		conditions.append(WorkflowSLAAlert.acknowledged == acknowledged)
	if severity:
		conditions.append(WorkflowSLAAlert.severity == severity)

	# Get total count
	count_stmt = select(func.count()).select_from(WorkflowSLAAlert).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	# Get alerts
	stmt = select(WorkflowSLAAlert).where(
		and_(*conditions)
	).order_by(WorkflowSLAAlert.created_at.desc()).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	alerts = result.scalars().all()

	return schema.SLAAlertsResponse(
		items=[schema.SLAAlertInfo.model_validate(a) for a in alerts],
		total=total or 0,
		page=page,
		page_size=page_size,
	)
