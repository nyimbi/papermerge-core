# (c) Copyright Datacraft, 2026
"""Routing Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class RuleCondition(BaseModel):
	"""Routing rule condition."""
	field: str
	operator: str  # equals, contains, starts_with, regex
	value: str


class RuleCreate(BaseModel):
	"""Schema for creating a routing rule."""
	name: str
	description: str | None = None
	priority: int = 100
	conditions: dict
	destination_type: str  # folder, workflow, user_inbox
	destination_id: UUID | None = None
	mode: str = "both"  # operational, archival, both


class RuleUpdate(BaseModel):
	"""Schema for updating a routing rule."""
	name: str | None = None
	description: str | None = None
	priority: int | None = None
	conditions: dict | None = None
	destination_type: str | None = None
	destination_id: UUID | None = None
	mode: str | None = None
	is_active: bool | None = None


class RuleInfo(BaseModel):
	"""Basic routing rule information."""
	id: UUID
	name: str
	priority: int
	destination_type: str
	mode: str
	is_active: bool
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class RuleDetail(BaseModel):
	"""Detailed routing rule information."""
	id: UUID
	name: str
	description: str | None = None
	priority: int
	conditions: dict
	destination_type: str
	destination_id: UUID | None = None
	mode: str
	is_active: bool
	created_at: datetime | None = None
	updated_at: datetime | None = None
	created_by: UUID | None = None

	model_config = ConfigDict(from_attributes=True)


class RuleListResponse(BaseModel):
	"""Paginated rule list."""
	items: list[RuleInfo]
	total: int
	page: int
	page_size: int


class RouteDocumentRequest(BaseModel):
	"""Request to route a document."""
	document_id: UUID
	mode: str = "operational"


class RouteDocumentResponse(BaseModel):
	"""Response from routing request."""
	success: bool
	matched: bool
	rule_id: UUID | None = None
	destination_type: str | None = None
	destination_id: UUID | None = None
	message: str | None = None


class RoutingLogInfo(BaseModel):
	"""Routing log entry."""
	id: UUID
	document_id: UUID
	rule_id: UUID | None = None
	matched: bool
	destination_type: str | None = None
	destination_id: UUID | None = None
	mode: str
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class RoutingLogListResponse(BaseModel):
	"""Paginated routing log list."""
	items: list[RoutingLogInfo]
	total: int
	page: int
	page_size: int


class TestRuleRequest(BaseModel):
	"""Request to test routing rules against metadata."""
	metadata: dict
	mode: str = "operational"


class TestRuleResponse(BaseModel):
	"""Response from test routing request."""
	matched: bool
	matching_rule: RuleInfo | None = None
