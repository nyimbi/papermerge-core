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


class ApprovalActionRequest(BaseModel):
	"""Request to submit an approval decision."""
	decision: str  # approved, rejected, returned
	notes: str | None = None


class WorkflowStatusResponse(BaseModel):
	"""Response with workflow instance status."""
	id: str
	workflow_id: str
	document_id: str
	status: str
	prefect_flow_run_id: str | None = None
	started_at: str | None = None
	completed_at: str | None = None

	model_config = ConfigDict(from_attributes=True)


class WorkflowExecution(BaseModel):
	"""Workflow execution (instance) information for listings."""
	id: UUID
	workflow_id: UUID
	workflow_name: str | None = None
	document_id: UUID
	status: str
	current_step_id: UUID | None = None
	started_at: datetime | None = None
	completed_at: datetime | None = None
	initiated_by: UUID | None = None
	prefect_flow_run_id: UUID | None = None

	model_config = ConfigDict(from_attributes=True)


class WorkflowExecutionListResponse(BaseModel):
	"""Paginated workflow executions list."""
	items: list[WorkflowExecution]
	total: int
	page: int
	page_size: int


# SLA Monitoring Schemas

class DelegationRequest(BaseModel):
	"""Request to delegate an approval request."""
	delegate_to_id: UUID
	reason: str | None = None


class EscalationLevelInfo(BaseModel):
	"""Escalation level information."""
	id: UUID
	level_order: int
	target_type: str
	target_id: UUID | None = None
	wait_hours: int
	notify_on_escalation: bool

	model_config = ConfigDict(from_attributes=True)


class EscalationChainInfo(BaseModel):
	"""Escalation chain information."""
	id: UUID
	name: str
	description: str | None = None
	is_active: bool
	levels: list[EscalationLevelInfo] = []

	model_config = ConfigDict(from_attributes=True)


class EscalationChainCreate(BaseModel):
	"""Request to create an escalation chain."""
	name: str
	description: str | None = None
	levels: list[dict]  # [{target_type, target_id, wait_hours, notify_on_escalation}]


class SLAConfigCreate(BaseModel):
	"""Request to create an SLA configuration."""
	name: str
	workflow_id: UUID | None = None
	step_id: UUID | None = None
	target_hours: int
	warning_threshold_percent: int = 75
	critical_threshold_percent: int = 90
	reminder_enabled: bool = True
	reminder_thresholds: list[int] | None = None
	escalation_chain_id: UUID | None = None


class SLAConfigInfo(BaseModel):
	"""SLA configuration information."""
	id: UUID
	name: str
	workflow_id: UUID | None = None
	step_id: UUID | None = None
	target_hours: int
	warning_threshold_percent: int
	critical_threshold_percent: int
	reminder_enabled: bool
	reminder_thresholds: list[int] | None = None
	escalation_chain_id: UUID | None = None
	is_active: bool
	created_at: datetime

	model_config = ConfigDict(from_attributes=True)


class TaskMetricInfo(BaseModel):
	"""Task metric information."""
	id: UUID
	workflow_id: UUID
	instance_id: UUID
	step_id: UUID | None = None
	step_type: str | None = None
	started_at: datetime
	completed_at: datetime | None = None
	target_at: datetime | None = None
	duration_seconds: int | None = None
	target_seconds: int | None = None
	sla_status: str
	breached_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class SLAAlertInfo(BaseModel):
	"""SLA alert information."""
	id: UUID
	alert_type: str
	severity: str
	title: str
	message: str | None = None
	workflow_id: UUID | None = None
	instance_id: UUID | None = None
	step_id: UUID | None = None
	assignee_id: UUID | None = None
	acknowledged: bool
	acknowledged_by: UUID | None = None
	acknowledged_at: datetime | None = None
	created_at: datetime

	model_config = ConfigDict(from_attributes=True)


class SLAAlertAcknowledgeRequest(BaseModel):
	"""Request to acknowledge an SLA alert."""
	notes: str | None = None


class SLADashboardStats(BaseModel):
	"""SLA dashboard statistics."""
	total_tasks: int
	on_track: int
	warning: int
	breached: int
	compliance_rate: float
	period_days: int


class SLADashboardResponse(BaseModel):
	"""SLA dashboard response."""
	stats: SLADashboardStats
	recent_alerts: list[SLAAlertInfo]
	recent_metrics: list[TaskMetricInfo]


class SLAMetricsResponse(BaseModel):
	"""Paginated SLA metrics response."""
	items: list[TaskMetricInfo]
	total: int
	page: int
	page_size: int


class SLAAlertsResponse(BaseModel):
	"""Paginated SLA alerts response."""
	items: list[SLAAlertInfo]
	total: int
	page: int
	page_size: int
