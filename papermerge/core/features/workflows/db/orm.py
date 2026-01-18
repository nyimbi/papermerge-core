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
