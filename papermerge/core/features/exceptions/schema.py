# (c) Copyright Datacraft, 2026
"""Exception Event Pydantic schemas."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Exception Events
# ---------------------------------------------------------------------------

class ExceptionEventCreate(BaseModel):
	"""Schema for creating an exception event (called by quality pipeline / scan agent)."""
	scan_job_id: str | None = None
	document_id: str | None = None
	batch_id: str | None = None
	page_number: int | None = None
	exception_type: str  # quality_rejected, missing_signature, incomplete_set, barcode_unreadable, orientation_error
	severity: str = "error"  # warning, error, critical
	routing_action: str | None = None
	description: str | None = None
	auto_fixable: bool = False
	quality_score: float | None = None
	defects: dict[str, Any] | None = None


class ExceptionEventUpdate(BaseModel):
	"""Partial update schema for an exception event."""
	status: str | None = None
	routing_action: str | None = None
	description: str | None = None
	resolution_notes: str | None = None


class ExceptionEventResolve(BaseModel):
	"""Schema for resolving an exception."""
	resolution_notes: str | None = None


class ExceptionEventDismiss(BaseModel):
	"""Schema for dismissing an exception."""
	resolution_notes: str | None = None


class ExceptionEventInfo(BaseModel):
	"""Full representation of an exception event."""
	id: str
	scan_job_id: str | None = None
	document_id: str | None = None
	batch_id: str | None = None
	page_number: int | None = None
	exception_type: str
	severity: str
	status: str
	routing_action: str | None = None
	description: str | None = None
	auto_fixable: bool
	quality_score: float | None = None
	defects: dict[str, Any] | None = None
	resolved_by_id: str | None = None
	resolved_at: datetime | None = None
	resolution_notes: str | None = None
	tenant_id: str | None = None
	created_at: datetime
	updated_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class ExceptionEventListResponse(BaseModel):
	"""Paginated list of exception events."""
	items: list[ExceptionEventInfo]
	total: int
	page: int
	page_size: int


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class ExceptionStatsInfo(BaseModel):
	"""Counts by type/status for dashboard widget."""
	total: int
	by_status: dict[str, int]
	by_type: dict[str, int]
	by_severity: dict[str, int]
	open_count: int
	critical_open: int


# ---------------------------------------------------------------------------
# Routing Rules
# ---------------------------------------------------------------------------

class RoutingRuleCreate(BaseModel):
	"""Schema for creating an exception routing rule."""
	exception_type: str
	action: str  # rescan_queue, supervisor_review, halt_batch, notify_operator, auto_dismiss
	priority: int = Field(default=100, ge=1)
	project_id: str | None = None
	is_active: bool = True
	config: dict[str, Any] | None = None


class RoutingRuleUpdate(BaseModel):
	"""Partial update for a routing rule."""
	exception_type: str | None = None
	action: str | None = None
	priority: int | None = Field(default=None, ge=1)
	project_id: str | None = None
	is_active: bool | None = None
	config: dict[str, Any] | None = None


class RoutingRuleInfo(BaseModel):
	"""Full representation of a routing rule."""
	id: str
	tenant_id: str | None = None
	project_id: str | None = None
	exception_type: str
	action: str
	priority: int
	is_active: bool
	config: dict[str, Any] | None = None
	created_at: datetime
	updated_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class RoutingRuleListResponse(BaseModel):
	"""List of routing rules."""
	items: list[RoutingRuleInfo]
	total: int
