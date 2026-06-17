# (c) Copyright Datacraft, 2026
"""ORM models for the workflow automation rules engine."""
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from papermerge.core.db.base import Base
from papermerge.core.utils.tz import utc_now


def _uuid7str() -> str:
	return str(uuid7())


class AutomationRule(Base):
	"""A rule that fires when a trigger event matches all conditions."""
	__tablename__ = "automation_rules"

	id: Mapped[str] = mapped_column(
		String(36),
		primary_key=True,
		default=_uuid7str,
	)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

	# Event that fires the rule
	# "document.classified" | "document.uploaded" | "document.expiring" | "scan.batch_complete"
	trigger_event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

	# JSON array of condition objects: [{field, operator, value}, ...]
	#   field:    document_type | tag_id | page_count | confidence_score
	#   operator: equals | not_equals | contains | greater_than | less_than
	conditions: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="'[]'")

	# JSON array of action objects: [{type, params}, ...]
	#   types: notify_user | assign_approval_workflow | route_to_folder | apply_tag
	#          | send_webhook | set_document_type
	actions: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="'[]'")

	is_active: Mapped[bool] = mapped_column(
		Boolean, nullable=False, default=True, server_default="true"
	)
	# Higher priority rules run first
	priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

	run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
	last_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

	tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
	created_by_id: Mapped[str] = mapped_column(String(36), nullable=False)
	created_at: Mapped[datetime] = mapped_column(
		TIMESTAMP(timezone=True),
		default=utc_now,
		nullable=False,
	)

	def __repr__(self) -> str:
		return f"AutomationRule(id={self.id!r}, name={self.name!r}, trigger={self.trigger_event!r})"
