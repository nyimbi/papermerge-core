# (c) Copyright Datacraft, 2026
"""Workflow ORM models."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import String, ForeignKey, Integer, Boolean, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSONB, ARRAY

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


class WorkflowStatus(str, Enum):
	PENDING = "pending"
	IN_PROGRESS = "in_progress"
	COMPLETED = "completed"
	REJECTED = "rejected"
	CANCELLED = "cancelled"
	ON_HOLD = "on_hold"


class StepType(str, Enum):
	APPROVAL = "approval"
	REVIEW = "review"
	ROUTE = "route"
	NOTIFY = "notify"
	CONDITION = "condition"
	ACTION = "action"
	PARALLEL = "parallel"


class StepStatus(str, Enum):
	PENDING = "pending"
	IN_PROGRESS = "in_progress"
	APPROVED = "approved"
	REJECTED = "rejected"
	SKIPPED = "skipped"
	ESCALATED = "escalated"


class ActionType(str, Enum):
	MOVE_TO_FOLDER = "move_to_folder"
	SET_STATUS = "set_status"
	SEND_EMAIL = "send_email"
	CALL_WEBHOOK = "call_webhook"
	ASSIGN_TAG = "assign_tag"
	SET_METADATA = "set_metadata"


class TriggerType(str, Enum):
	MANUAL = "manual"
	AUTO = "auto"
	SCHEDULED = "scheduled"


class WorkflowMode(str, Enum):
	OPERATIONAL = "operational"
	ARCHIVAL = "archival"
	BOTH = "both"


class Workflow(Base):
	"""Workflow definition."""
	__tablename__ = "workflows"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)

	name: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)
	category: Mapped[str | None] = mapped_column(String(100))

	# Trigger
	trigger_type: Mapped[str] = mapped_column(
		String(50), default=TriggerType.MANUAL.value, nullable=False
	)
	trigger_conditions: Mapped[dict | None] = mapped_column(JSONB)

	# Mode
	mode: Mapped[str] = mapped_column(
		String(20), default=WorkflowMode.OPERATIONAL.value, nullable=False
	)

	is_active: Mapped[bool] = mapped_column(Boolean, default=True)

	# Prefect integration
	prefect_deployment_id: Mapped[UUID | None] = mapped_column()

	# React Flow graph storage
	nodes: Mapped[list | None] = mapped_column(JSONB)
	edges: Mapped[list | None] = mapped_column(JSONB)
	viewport: Mapped[dict | None] = mapped_column(JSONB)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)
	created_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	# Relationships
	steps: Mapped[list["WorkflowStep"]] = relationship(
		"WorkflowStep", back_populates="workflow", cascade="all, delete-orphan",
		order_by="WorkflowStep.step_order"
	)
	instances: Mapped[list["WorkflowInstance"]] = relationship(
		"WorkflowInstance", back_populates="workflow"
	)

	__table_args__ = (
		Index("idx_workflows_tenant_active", "tenant_id", "is_active"),
	)


class WorkflowStep(Base):
	"""Workflow step/node definition."""
	__tablename__ = "workflow_steps"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	workflow_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
	)

	name: Mapped[str] = mapped_column(String(100), nullable=False)
	step_type: Mapped[str] = mapped_column(String(50), nullable=False)
	step_order: Mapped[int] = mapped_column(Integer, nullable=False)

	# React Flow node reference
	node_id: Mapped[str | None] = mapped_column(String(100))
	config: Mapped[dict | None] = mapped_column(JSONB)

	# Assignment
	assignee_type: Mapped[str | None] = mapped_column(String(50))
	assignee_id: Mapped[UUID | None] = mapped_column()
	assignee_expression: Mapped[str | None] = mapped_column(String(255))

	# Conditions
	condition_expression: Mapped[str | None] = mapped_column(Text)

	# Actions
	action_type: Mapped[str | None] = mapped_column(String(50))
	action_config: Mapped[dict | None] = mapped_column(JSONB)

	# Timeouts
	deadline_hours: Mapped[int | None] = mapped_column(Integer)
	escalation_step_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_steps.id", ondelete="SET NULL")
	)

	# SLA configuration
	sla_config_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_task_sla_configs.id", ondelete="SET NULL")
	)
	reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	# Relationships
	workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="steps")
	executions: Mapped[list["WorkflowStepExecution"]] = relationship(
		"WorkflowStepExecution", back_populates="step"
	)


class WorkflowInstance(Base):
	"""Running workflow instance."""
	__tablename__ = "workflow_instances"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	workflow_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
	)
	document_id: Mapped[UUID] = mapped_column(
		ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
	)

	current_step_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_steps.id", ondelete="SET NULL")
	)
	status: Mapped[str] = mapped_column(
		String(50), default=WorkflowStatus.PENDING.value, nullable=False
	)

	# Prefect integration
	prefect_flow_run_id: Mapped[UUID | None] = mapped_column(unique=True)

	# Timing
	started_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	initiated_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)
	context: Mapped[dict | None] = mapped_column(JSONB)

	# Relationships
	workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="instances")
	current_step: Mapped["WorkflowStep | None"] = relationship(
		"WorkflowStep", foreign_keys=[current_step_id]
	)
	executions: Mapped[list["WorkflowStepExecution"]] = relationship(
		"WorkflowStepExecution", back_populates="instance", cascade="all, delete-orphan"
	)

	__table_args__ = (
		Index("idx_workflow_instances_status", "status"),
		Index("idx_workflow_instances_document", "document_id"),
	)


class WorkflowStepExecution(Base):
	"""Individual step execution record."""
	__tablename__ = "workflow_step_executions"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	instance_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False, index=True
	)
	step_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=False
	)

	status: Mapped[str] = mapped_column(
		String(50), default=StepStatus.PENDING.value, nullable=False
	)
	assigned_to: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	# Prefect integration
	prefect_task_run_id: Mapped[UUID | None] = mapped_column(index=True)
	result_data: Mapped[dict | None] = mapped_column(JSONB)
	error_message: Mapped[str | None] = mapped_column(Text)
	retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

	# Timing
	started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	deadline_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Response
	action_taken: Mapped[str | None] = mapped_column(String(50))
	comments: Mapped[str | None] = mapped_column(Text)
	attachments: Mapped[list[UUID] | None] = mapped_column(ARRAY(String))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	# Relationships
	instance: Mapped["WorkflowInstance"] = relationship(
		"WorkflowInstance", back_populates="executions"
	)
	step: Mapped["WorkflowStep"] = relationship(
		"WorkflowStep", back_populates="executions"
	)

	__table_args__ = (
		Index("idx_step_executions_pending", "status", "deadline_at"),
	)


class SLAStatus(str, Enum):
	ON_TRACK = "on_track"
	WARNING = "warning"
	BREACHED = "breached"


class EscalationTargetType(str, Enum):
	USER = "user"
	ROLE = "role"
	MANAGER = "manager"


class WorkflowEscalationChain(Base):
	"""Multi-level escalation configuration."""
	__tablename__ = "workflow_escalation_chains"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)
	name: Mapped[str] = mapped_column(String(100), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)

	levels: Mapped[list["WorkflowEscalationLevel"]] = relationship(
		"WorkflowEscalationLevel", back_populates="chain", cascade="all, delete-orphan",
		order_by="WorkflowEscalationLevel.level_order"
	)


class WorkflowEscalationLevel(Base):
	"""Individual escalation level (user/role/manager)."""
	__tablename__ = "workflow_escalation_levels"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	chain_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflow_escalation_chains.id", ondelete="CASCADE"), nullable=False, index=True
	)
	level_order: Mapped[int] = mapped_column(Integer, nullable=False)
	target_type: Mapped[str] = mapped_column(String(20), nullable=False)  # user, role, manager
	target_id: Mapped[UUID | None] = mapped_column()  # user_id or role_id
	wait_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
	notify_on_escalation: Mapped[bool] = mapped_column(Boolean, default=True)

	chain: Mapped["WorkflowEscalationChain"] = relationship(
		"WorkflowEscalationChain", back_populates="levels"
	)


class WorkflowTaskSLAConfig(Base):
	"""SLA thresholds per workflow/step."""
	__tablename__ = "workflow_task_sla_configs"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)
	workflow_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflows.id", ondelete="CASCADE")
	)
	step_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_steps.id", ondelete="CASCADE")
	)
	name: Mapped[str] = mapped_column(String(100), nullable=False)

	# SLA thresholds (in hours)
	target_hours: Mapped[int] = mapped_column(Integer, nullable=False)
	warning_threshold_percent: Mapped[int] = mapped_column(Integer, default=75)
	critical_threshold_percent: Mapped[int] = mapped_column(Integer, default=90)

	# Reminder configuration
	reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
	reminder_thresholds: Mapped[list | None] = mapped_column(JSONB)  # [50, 75, 90] percent

	escalation_chain_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_escalation_chains.id", ondelete="SET NULL")
	)

	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	__table_args__ = (
		Index("idx_sla_config_workflow", "workflow_id"),
		Index("idx_sla_config_step", "step_id"),
	)


class WorkflowTaskMetric(Base):
	"""Execution timing metrics for SLA tracking."""
	__tablename__ = "workflow_task_metrics"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)
	workflow_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
	)
	instance_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False
	)
	step_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_steps.id", ondelete="SET NULL")
	)
	execution_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_step_executions.id", ondelete="SET NULL")
	)

	step_type: Mapped[str | None] = mapped_column(String(50))
	sla_config_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_task_sla_configs.id", ondelete="SET NULL")
	)

	# Timing
	started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
	completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	target_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Duration in seconds
	duration_seconds: Mapped[int | None] = mapped_column(Integer)
	target_seconds: Mapped[int | None] = mapped_column(Integer)

	# Status
	sla_status: Mapped[str] = mapped_column(
		String(20), default=SLAStatus.ON_TRACK.value, nullable=False
	)
	breached_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	__table_args__ = (
		Index("idx_task_metrics_sla_status", "sla_status", "tenant_id"),
		Index("idx_task_metrics_workflow", "workflow_id", "created_at"),
	)


class WorkflowSLAAlert(Base):
	"""Generated SLA alerts."""
	__tablename__ = "workflow_sla_alerts"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	tenant_id: Mapped[UUID] = mapped_column(
		ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
	)
	metric_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_task_metrics.id", ondelete="SET NULL")
	)
	approval_request_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_approval_requests.id", ondelete="SET NULL")
	)

	alert_type: Mapped[str] = mapped_column(String(30), nullable=False)  # warning, breach, escalation
	severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
	title: Mapped[str] = mapped_column(String(255), nullable=False)
	message: Mapped[str | None] = mapped_column(Text)

	workflow_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflows.id", ondelete="SET NULL")
	)
	instance_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_instances.id", ondelete="SET NULL")
	)
	step_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_steps.id", ondelete="SET NULL")
	)

	assignee_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
	acknowledged_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)
	acknowledged_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)

	__table_args__ = (
		Index("idx_sla_alerts_unack", "tenant_id", "acknowledged"),
		Index("idx_sla_alerts_assignee", "assignee_id", "acknowledged"),
	)


class WorkflowApprovalReminder(Base):
	"""Track sent reminders for approval requests."""
	__tablename__ = "workflow_approval_reminders"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	approval_request_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflow_approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
	)
	threshold_percent: Mapped[int] = mapped_column(Integer, nullable=False)  # 50, 75, 90
	sent_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email, in_app, webhook


class WorkflowApprovalRequest(Base):
	"""Human-in-the-loop approval requests."""
	__tablename__ = "workflow_approval_requests"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	instance_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False, index=True
	)
	step_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=False
	)
	execution_id: Mapped[UUID] = mapped_column(
		ForeignKey("workflow_step_executions.id", ondelete="CASCADE"), nullable=False
	)

	prefect_flow_run_id: Mapped[UUID | None] = mapped_column(index=True)

	approval_type: Mapped[str] = mapped_column(String(50), nullable=False)  # approval, review, signature
	title: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)

	document_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("nodes.id", ondelete="SET NULL")
	)
	requester_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	# Assignment (one of these)
	assignee_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)
	assignee_role_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("roles.id", ondelete="SET NULL")
	)
	assignee_group_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("groups.id", ondelete="SET NULL")
	)

	status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
	priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)

	# Decision
	decision: Mapped[str | None] = mapped_column(String(50))
	decision_notes: Mapped[str | None] = mapped_column(Text)
	decided_by: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)
	decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

	# Deadline and escalation
	deadline_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	escalation_chain_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("workflow_escalation_chains.id", ondelete="SET NULL")
	)
	current_escalation_level: Mapped[int] = mapped_column(Integer, default=0)
	escalated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	escalated_to: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)

	# Reminder tracking
	reminder_sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	last_reminder_threshold: Mapped[int | None] = mapped_column(Integer)

	# Delegation
	delegated_from_id: Mapped[UUID | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL")
	)
	delegated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
	delegation_reason: Mapped[str | None] = mapped_column(Text)

	context_data: Mapped[dict | None] = mapped_column(JSONB)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True), default=utc_now, onupdate=func.now(), nullable=False
	)

	reminders: Mapped[list["WorkflowApprovalReminder"]] = relationship(
		"WorkflowApprovalReminder", cascade="all, delete-orphan"
	)

	__table_args__ = (
		Index("idx_approval_requests_assignee_status", "assignee_id", "status"),
		Index("idx_approval_requests_deadline_status", "deadline_at", "status"),
	)
