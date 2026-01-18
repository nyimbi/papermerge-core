# User Home Page Views (Pydantic Schemas)
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class UserInfo(BaseModel):
	"""User basic info for home page."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	name: str
	email: str
	avatar_url: str | None = None
	department: str | None = None
	role: str | None = None


class UserStats(BaseModel):
	"""User statistics for home page."""
	pending_tasks: int = 0
	documents_this_week: int = 0
	approvals_pending: int = 0
	deadlines_upcoming: int = 0


class TaskActor(BaseModel):
	"""Task actor/assigner info."""
	id: str
	name: str
	avatar_url: str | None = None


class TaskAction(BaseModel):
	"""Available action for a workflow task."""
	id: str
	label: str
	type: Literal['approve', 'reject', 'complete', 'forward', 'comment', 'custom']
	requires_comment: bool = False
	next_step: str | None = None


class WorkflowTaskOut(BaseModel):
	"""Workflow task response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	title: str
	description: str | None = None
	workflow_name: str
	workflow_id: str
	document_id: str | None = None
	document_title: str | None = None
	priority: Literal['urgent', 'high', 'medium', 'low']
	status: Literal['pending', 'in_progress', 'completed', 'overdue']
	due_date: datetime | None = None
	assigned_at: datetime
	assigned_by: TaskActor | None = None
	actions: list[TaskAction] = []


class DocumentTag(BaseModel):
	"""Document tag."""
	id: str
	name: str
	color: str


class RecentDocumentOut(BaseModel):
	"""Recent document response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	title: str
	path: str
	type: Literal['pdf', 'doc', 'docx', 'xls', 'xlsx', 'img', 'other']
	thumbnail_url: str | None = None
	accessed_at: datetime
	access_type: Literal['viewed', 'edited', 'shared']
	size_bytes: int
	page_count: int | None = None
	tags: list[DocumentTag] = []


class FavoriteItemOut(BaseModel):
	"""Favorite item response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	item_type: Literal['document', 'folder', 'search', 'workflow']
	item_id: str
	title: str
	path: str | None = None
	icon: str | None = None
	pinned_at: datetime


class ActivityActorOut(BaseModel):
	"""Activity actor."""
	id: str
	name: str
	avatar_url: str | None = None


class ActivityEventOut(BaseModel):
	"""Activity event response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	type: Literal['view', 'edit', 'share', 'upload', 'comment', 'approve', 'reject']
	title: str
	description: str | None = None
	document_id: str | None = None
	document_title: str | None = None
	actor: ActivityActorOut | None = None
	timestamp: datetime
	metadata: dict | None = None


class NotificationOut(BaseModel):
	"""Notification response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	type: Literal['task', 'mention', 'share', 'comment', 'system', 'deadline']
	title: str
	message: str
	is_read: bool = False
	link: str | None = None
	created_at: datetime
	metadata: dict | None = None


class CalendarEventOut(BaseModel):
	"""Calendar event response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	title: str
	type: Literal['deadline', 'reminder', 'meeting', 'task']
	date: datetime
	document_id: str | None = None
	workflow_id: str | None = None
	is_all_day: bool = False
	color: str | None = None


class RecentSearchOut(BaseModel):
	"""Recent search response."""
	model_config = ConfigDict(from_attributes=True)

	id: str
	query: str
	filters: dict | None = None
	result_count: int = 0
	searched_at: datetime


class UserHomeDataOut(BaseModel):
	"""Complete user home page data."""
	user: UserInfo
	stats: UserStats
	tasks: list[WorkflowTaskOut] = []
	recent_documents: list[RecentDocumentOut] = []
	favorites: list[FavoriteItemOut] = []
	activity: list[ActivityEventOut] = []
	notifications: list[NotificationOut] = []
	calendar_events: list[CalendarEventOut] = []
	recent_searches: list[RecentSearchOut] = []


# Request schemas
class FavoriteItemCreate(BaseModel):
	"""Create favorite item request."""
	model_config = ConfigDict(extra='forbid')

	item_type: Literal['document', 'folder', 'search', 'workflow']
	item_id: str
	title: str
	path: str | None = None


class TaskActionRequest(BaseModel):
	"""Task action request."""
	model_config = ConfigDict(extra='forbid')

	action_id: str
	comment: str | None = None
	metadata: dict | None = None
