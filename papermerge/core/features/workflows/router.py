# (c) Copyright Datacraft, 2026
"""Workflow management API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.services.workflow_engine import WorkflowEngine
from . import schema

router = APIRouter(
	prefix="/workflows",
	tags=["workflows"],
)

logger = logging.getLogger(__name__)


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
	db_session: AsyncSession = Depends(get_db),
) -> schema.WorkflowInstanceInfo:
	"""Start a workflow for a document."""
	engine = WorkflowEngine(db_session)

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
	db_session: AsyncSession = Depends(get_db),
) -> schema.PendingTasksResponse:
	"""Get pending workflow tasks for current user."""
	engine = WorkflowEngine(db_session)
	tasks = await engine.get_pending_tasks(user.id)

	return schema.PendingTasksResponse(
		tasks=[schema.PendingTask.model_validate(t) for t in tasks]
	)


@router.post("/instances/{instance_id}/actions")
async def process_workflow_action(
	instance_id: UUID,
	action: schema.WorkflowActionRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.WorkflowInstanceInfo:
	"""Process an action on a workflow step."""
	engine = WorkflowEngine(db_session)

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
	db_session: AsyncSession = Depends(get_db),
) -> schema.WorkflowInstanceInfo:
	"""Cancel a running workflow."""
	engine = WorkflowEngine(db_session)

	try:
		instance = await engine.cancel_workflow(
			instance_id=instance_id,
			user_id=user.id,
			reason=request.reason,
		)
		return schema.WorkflowInstanceInfo.model_validate(instance)
	except ValueError as e:
		raise HTTPException(status_code=400, detail=str(e))
