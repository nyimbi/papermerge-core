# (c) Copyright Datacraft, 2026
"""Workflow Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class WorkflowStepCreate(BaseModel):
	"""Schema for creating a workflow step."""
	name: str
	assignee_type: str = "user"
	assignee_id: UUID | None = None
	deadline_hours: int | None = None


class WorkflowCreate(BaseModel):
	"""Schema for creating a workflow."""
	name: str
	description: str | None = None
	steps: list[WorkflowStepCreate]


class WorkflowInfo(BaseModel):
	"""Basic workflow information."""
	id: UUID
	name: str
	description: str | None = None
	is_active: bool
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class WorkflowStepInfo(BaseModel):
	"""Workflow step information."""
	id: UUID
	name: str
	step_order: int
	assignee_type: str | None = None
	assignee_id: UUID | None = None
	deadline_hours: int | None = None

	model_config = ConfigDict(from_attributes=True)


class WorkflowDetail(BaseModel):
	"""Detailed workflow information with steps."""
	id: UUID
	name: str
	description: str | None = None
	is_active: bool
	steps: list[WorkflowStepInfo] = []
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class WorkflowListResponse(BaseModel):
	"""Paginated workflow list."""
	items: list[WorkflowInfo]
	total: int
	page: int
	page_size: int


class WorkflowStartRequest(BaseModel):
	"""Request to start a workflow."""
	document_id: UUID
	context: dict | None = None


class WorkflowInstanceInfo(BaseModel):
	"""Workflow instance information."""
	id: UUID
	workflow_id: UUID
	document_id: UUID
	status: str
	current_step_id: UUID | None = None
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class PendingTask(BaseModel):
	"""Pending workflow task."""
	id: UUID
	instance_id: UUID
	step_id: UUID
	status: str
	assigned_to: UUID | None = None
	deadline_at: datetime | None = None
	started_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class PendingTasksResponse(BaseModel):
	"""Response with pending tasks."""
	tasks: list[PendingTask]


class WorkflowActionRequest(BaseModel):
	"""Request to process a workflow action."""
	execution_id: UUID
	action: str  # approved, rejected, returned, forwarded
	comments: str | None = None


class WorkflowCancelRequest(BaseModel):
	"""Request to cancel a workflow."""
	reason: str | None = None
