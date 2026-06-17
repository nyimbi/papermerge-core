# (c) Copyright Datacraft, 2026
"""Approval workflow REST endpoints — auto-discovered by router_loader."""
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from papermerge.core import schema
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.utils.tz import utc_now
from .db.orm import ApprovalStep, ApprovalWorkflow
from .service import advance_workflow

# Single router — no prefix; all paths are explicit full paths.
router = APIRouter(tags=["approvals"])

_log = logging.getLogger(__name__)


def _uuid7str() -> str:
	from uuid6 import uuid7
	return str(uuid7())


# ── Pydantic I/O schemas ──────────────────────────────────────────────────────

class StepIn(BaseModel):
	approver_email: str
	approver_user_id: str | None = None


class CreateWorkflowIn(BaseModel):
	name: str
	steps: list[StepIn]


class StepOut(BaseModel):
	id: str
	step_order: int
	approver_email: str
	approver_user_id: str | None
	status: str
	comment: str | None
	decided_at: datetime | None

	class Config:
		from_attributes = True


class WorkflowOut(BaseModel):
	id: str
	document_id: str
	name: str
	status: str
	created_by_id: str
	tenant_id: str
	created_at: datetime
	completed_at: datetime | None
	steps: list[StepOut]

	class Config:
		from_attributes = True


class ApproveIn(BaseModel):
	comment: str | None = None


class RejectIn(BaseModel):
	comment: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
	"/documents/{document_id}/approval-workflows",
	response_model=WorkflowOut,
	status_code=status.HTTP_201_CREATED,
)
async def create_approval_workflow(
	document_id: str,
	body: CreateWorkflowIn,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> WorkflowOut:
	"""Create a new approval workflow with ordered steps for a document."""
	if not body.steps:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="At least one approval step is required.",
		)

	workflow = ApprovalWorkflow(
		id=_uuid7str(),
		document_id=document_id,
		name=body.name,
		status="in_review",
		created_by_id=str(current_user.id),
		tenant_id=str(current_user.tenant_id),
		created_at=utc_now(),
	)
	db_session.add(workflow)

	for order, step_in in enumerate(body.steps, start=1):
		step = ApprovalStep(
			id=_uuid7str(),
			workflow_id=workflow.id,
			step_order=order,
			approver_email=step_in.approver_email,
			approver_user_id=step_in.approver_user_id,
			status="pending",
		)
		db_session.add(step)

	await db_session.flush()

	# Notify the first approver
	first_stmt = (
		select(ApprovalStep)
		.where(ApprovalStep.workflow_id == workflow.id)
		.order_by(ApprovalStep.step_order)
		.limit(1)
	)
	first_result = await db_session.execute(first_stmt)
	first_step = first_result.scalar_one_or_none()
	if first_step:
		from .service import notify_approver
		await notify_approver(first_step, f"document {document_id}", db_session)

	await db_session.commit()

	# Reload with steps for response
	stmt = (
		select(ApprovalWorkflow)
		.options(selectinload(ApprovalWorkflow.steps))
		.where(ApprovalWorkflow.id == workflow.id)
	)
	result = await db_session.execute(stmt)
	workflow = result.scalar_one()
	return WorkflowOut.model_validate(workflow)


@router.get(
	"/documents/{document_id}/approval-workflows",
	response_model=list[WorkflowOut],
)
async def list_approval_workflows(
	document_id: str,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> list[WorkflowOut]:
	"""Return all approval workflows for a document."""
	stmt = (
		select(ApprovalWorkflow)
		.options(selectinload(ApprovalWorkflow.steps))
		.where(ApprovalWorkflow.document_id == document_id)
		.order_by(ApprovalWorkflow.created_at.desc())
	)
	result = await db_session.execute(stmt)
	workflows = result.scalars().all()
	return [WorkflowOut.model_validate(w) for w in workflows]


@router.post(
	"/approval-workflows/{workflow_id}/steps/{step_id}/approve",
	response_model=WorkflowOut,
)
async def approve_step(
	workflow_id: str,
	step_id: str,
	body: ApproveIn,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> WorkflowOut:
	"""Approve a single step; advance the workflow."""
	step_stmt = select(ApprovalStep).where(
		ApprovalStep.id == step_id,
		ApprovalStep.workflow_id == workflow_id,
	)
	step_result = await db_session.execute(step_stmt)
	step = step_result.scalar_one_or_none()
	if step is None:
		raise HTTPException(status_code=404, detail="Step not found.")
	if step.status != "pending":
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail=f"Step is already {step.status}.",
		)

	step.status = "approved"
	step.comment = body.comment
	step.decided_at = utc_now()

	await db_session.flush()
	await advance_workflow(workflow_id, db_session)
	await db_session.commit()

	wf_stmt = (
		select(ApprovalWorkflow)
		.options(selectinload(ApprovalWorkflow.steps))
		.where(ApprovalWorkflow.id == workflow_id)
	)
	wf_result = await db_session.execute(wf_stmt)
	workflow = wf_result.scalar_one()
	return WorkflowOut.model_validate(workflow)


@router.post(
	"/approval-workflows/{workflow_id}/steps/{step_id}/reject",
	response_model=WorkflowOut,
)
async def reject_step(
	workflow_id: str,
	step_id: str,
	body: RejectIn,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> WorkflowOut:
	"""Reject a step and mark the whole workflow rejected."""
	step_stmt = select(ApprovalStep).where(
		ApprovalStep.id == step_id,
		ApprovalStep.workflow_id == workflow_id,
	)
	step_result = await db_session.execute(step_stmt)
	step = step_result.scalar_one_or_none()
	if step is None:
		raise HTTPException(status_code=404, detail="Step not found.")
	if step.status != "pending":
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail=f"Step is already {step.status}.",
		)

	step.status = "rejected"
	step.comment = body.comment
	step.decided_at = utc_now()

	wf_stmt = select(ApprovalWorkflow).where(ApprovalWorkflow.id == workflow_id)
	wf_result = await db_session.execute(wf_stmt)
	workflow = wf_result.scalar_one()
	workflow.status = "rejected"
	workflow.completed_at = utc_now()

	await db_session.commit()

	wf_stmt2 = (
		select(ApprovalWorkflow)
		.options(selectinload(ApprovalWorkflow.steps))
		.where(ApprovalWorkflow.id == workflow_id)
	)
	wf_result2 = await db_session.execute(wf_stmt2)
	workflow = wf_result2.scalar_one()
	return WorkflowOut.model_validate(workflow)
