# (c) Copyright Datacraft, 2026
"""ORM models for multi-step document approval workflows."""
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid6 import uuid7

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


def _uuid7str() -> str:
	return str(uuid7())


class ApprovalWorkflow(Base):
	"""A named approval workflow tied to a document."""
	__tablename__ = "approval_workflows"

	id: Mapped[str] = mapped_column(
		String(36),
		primary_key=True,
		default=_uuid7str,
	)
	document_id: Mapped[str] = mapped_column(
		String(36),
		nullable=False,
		index=True,
	)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	# "in_review" | "approved" | "rejected"
	status: Mapped[str] = mapped_column(
		String(20),
		nullable=False,
		default="in_review",
		server_default="in_review",
	)
	created_by_id: Mapped[str] = mapped_column(String(36), nullable=False)
	tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)
	completed_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True),
		nullable=True,
	)

	steps: Mapped[list["ApprovalStep"]] = relationship(
		"ApprovalStep",
		back_populates="workflow",
		order_by="ApprovalStep.step_order",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return f"ApprovalWorkflow(id={self.id!r}, doc={self.document_id!r}, status={self.status!r})"


class ApprovalStep(Base):
	"""A single approver step within an ApprovalWorkflow."""
	__tablename__ = "approval_steps"

	id: Mapped[str] = mapped_column(
		String(36),
		primary_key=True,
		default=_uuid7str,
	)
	workflow_id: Mapped[str] = mapped_column(
		String(36),
		ForeignKey("approval_workflows.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	step_order: Mapped[int] = mapped_column(Integer, nullable=False)
	approver_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
	approver_email: Mapped[str] = mapped_column(String(255), nullable=False)
	# "pending" | "approved" | "rejected" | "skipped"
	status: Mapped[str] = mapped_column(
		String(20),
		nullable=False,
		default="pending",
		server_default="pending",
	)
	comment: Mapped[str | None] = mapped_column(Text, nullable=True)
	decided_at: Mapped[datetime | None] = mapped_column(
		TIMESTAMP(timezone=True),
		nullable=True,
	)

	workflow: Mapped["ApprovalWorkflow"] = relationship(
		"ApprovalWorkflow",
		back_populates="steps",
	)

	def __repr__(self) -> str:
		return f"ApprovalStep(id={self.id!r}, order={self.step_order}, status={self.status!r})"
