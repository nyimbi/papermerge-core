# User Home Page Service
import logging
import uuid
from datetime import datetime, timedelta, timezone

from papermerge.core.utils.uuid_compat import uuid7str

from sqlalchemy import select, func, delete, update, desc, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.models import User, Document, DocumentVersion
from papermerge.core.features.ownership.db.orm import Ownership
from .models import UserNotification, UserFavorite, UserSearchHistory
from .views import (
	UserHomeDataOut, UserInfo, UserStats, WorkflowTaskOut,
	RecentDocumentOut, FavoriteItemOut, ActivityEventOut, NotificationOut,
	CalendarEventOut, RecentSearchOut, FavoriteItemCreate,
	ActivityActorOut,
)

# Lazy imports to avoid circular dependencies — imported inside methods
def _workflow_orm():
	from papermerge.core.features.workflows.db.orm import (
		WorkflowStepExecution, WorkflowStep, WorkflowInstance, Workflow,
		WorkflowApprovalRequest,
	)
	return WorkflowStepExecution, WorkflowStep, WorkflowInstance, Workflow, WorkflowApprovalRequest

def _audit_orm():
	from papermerge.core.features.audit.db.orm import AuditLog
	return AuditLog

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
	return datetime.now(tz=timezone.utc)


class UserHomeService:
	"""Service for user home page data aggregation."""

	def __init__(self, session: AsyncSession):
		self.session = session

	async def get_user_home_data(
		self,
		user_id: str,
		tenant_id: str | None = None,
	) -> UserHomeDataOut:
		"""Get aggregated home page data for a user."""
		user_info = await self._get_user_info(user_id)

		stats = await self._get_user_stats(user_id, tenant_id)
		tasks = await self._get_workflow_tasks(user_id, tenant_id, limit=10)
		recent_docs = await self._get_recent_documents(user_id, tenant_id, limit=10)
		favorites = await self._get_favorites(user_id, tenant_id, limit=10)
		activity = await self._get_activity_feed(user_id, tenant_id, limit=10)
		notifications = await self._get_notifications(user_id, limit=20)
		calendar_events = await self._get_calendar_events(user_id, tenant_id)
		recent_searches = await self._get_recent_searches(user_id, limit=10)

		return UserHomeDataOut(
			user=user_info,
			stats=stats,
			tasks=tasks,
			recent_documents=recent_docs,
			favorites=favorites,
			activity=activity,
			notifications=notifications,
			calendar_events=calendar_events,
			recent_searches=recent_searches,
		)

	async def _get_user_info(self, user_id: str) -> UserInfo:
		"""Get user basic info."""
		stmt = select(User).where(User.id == user_id)
		result = await self.session.execute(stmt)
		user = result.scalar_one_or_none()

		if not user:
			raise ValueError(f"User {user_id} not found")

		name = user.username
		if hasattr(user, 'first_name') and hasattr(user, 'last_name'):
			if user.first_name or user.last_name:
				name = f"{user.first_name or ''} {user.last_name or ''}".strip()

		return UserInfo(
			id=str(user.id),
			name=name,
			email=user.email,
			avatar_url=getattr(user, 'avatar_url', None),
			department=getattr(user, 'department', None),
			role=getattr(user, 'role_name', None),
		)

	async def _get_user_stats(
		self,
		user_id: str,
		tenant_id: str | None = None,
	) -> UserStats:
		"""Get user statistics."""
		now = _utcnow()
		week_ago = now - timedelta(days=7)
		next_week = now + timedelta(days=7)
		uid = uuid.UUID(user_id)

		WorkflowStepExecution, WorkflowStep, WorkflowInstance, Workflow, WorkflowApprovalRequest = _workflow_orm()

		# Documents this week owned by this user
		doc_stmt = (
			select(func.count(Document.id))
			.join(Ownership, and_(
				Ownership.resource_id == Document.id,
				Ownership.resource_type == "node",
				Ownership.owner_type == "user",
				Ownership.owner_id == uid,
			))
			.where(Document.created_at >= week_ago)
		)
		docs_this_week = (await self.session.scalar(doc_stmt)) or 0

		# Pending workflow tasks assigned to user
		pending_stmt = (
			select(func.count(WorkflowStepExecution.id))
			.where(
				WorkflowStepExecution.assigned_to == uid,
				WorkflowStepExecution.status.in_(["pending", "in_progress"]),
			)
		)
		pending_tasks = (await self.session.scalar(pending_stmt)) or 0

		# Pending approvals assigned to user
		approvals_stmt = (
			select(func.count(WorkflowApprovalRequest.id))
			.where(
				WorkflowApprovalRequest.assignee_id == uid,
				WorkflowApprovalRequest.status == "pending",
			)
		)
		approvals_pending = (await self.session.scalar(approvals_stmt)) or 0

		# Upcoming deadlines: step executions assigned to user with deadline in next 7 days
		deadlines_stmt = (
			select(func.count(WorkflowStepExecution.id))
			.where(
				WorkflowStepExecution.assigned_to == uid,
				WorkflowStepExecution.deadline_at >= now,
				WorkflowStepExecution.deadline_at <= next_week,
				WorkflowStepExecution.status.in_(["pending", "in_progress"]),
			)
		)
		deadlines_upcoming = (await self.session.scalar(deadlines_stmt)) or 0

		return UserStats(
			pending_tasks=pending_tasks,
			documents_this_week=docs_this_week,
			approvals_pending=approvals_pending,
			deadlines_upcoming=deadlines_upcoming,
		)

	async def _get_workflow_tasks(
		self,
		user_id: str,
		tenant_id: str | None = None,
		limit: int = 10,
	) -> list[WorkflowTaskOut]:
		"""Get pending workflow tasks assigned to user from workflow_step_executions."""
		WorkflowStepExecution, WorkflowStep, WorkflowInstance, Workflow, WorkflowApprovalRequest = _workflow_orm()
		uid = uuid.UUID(str(user_id))
		now = datetime.now(timezone.utc)

		stmt = (
			select(
				WorkflowStepExecution,
				WorkflowStep.name.label("step_name"),
				WorkflowInstance.document_id,
				Workflow.name.label("workflow_name"),
				Workflow.id.label("workflow_id"),
			)
			.join(WorkflowStep, WorkflowStepExecution.step_id == WorkflowStep.id)
			.join(WorkflowInstance, WorkflowStepExecution.instance_id == WorkflowInstance.id)
			.join(Workflow, WorkflowInstance.workflow_id == Workflow.id)
			.where(
				WorkflowStepExecution.assigned_to == uid,
				WorkflowStepExecution.status.in_(["pending", "in_progress"]),
			)
			.order_by(WorkflowStepExecution.deadline_at.asc().nulls_last())
			.limit(limit)
		)
		result = await self.session.execute(stmt)
		rows = result.all()

		tasks = []
		for row in rows:
			exe, step_name, document_id, workflow_name, workflow_id = row
			if exe.status == "in_progress":
				task_status = "in_progress"
			elif exe.deadline_at and exe.deadline_at < now:
				task_status = "overdue"
			else:
				task_status = "pending"

			tasks.append(WorkflowTaskOut(
				id=str(exe.id),
				title=step_name,
				workflow_name=workflow_name,
				workflow_id=str(workflow_id),
				document_id=str(document_id) if document_id else None,
				priority="medium",
				status=task_status,
				due_date=exe.deadline_at,
				assigned_at=exe.started_at or now,
			))
		return tasks

	async def _get_recent_documents(
		self,
		user_id: str,
		tenant_id: str | None = None,
		limit: int = 10,
	) -> list[RecentDocumentOut]:
		"""Get recently accessed documents for user via Ownership join."""
		uid = uuid.UUID(user_id)

		# Subquery: latest DocumentVersion size per document
		latest_ver = (
			select(
				DocumentVersion.document_id,
				func.max(DocumentVersion.created_at).label("max_created"),
			)
			.group_by(DocumentVersion.document_id)
			.subquery()
		)
		ver_size = (
			select(DocumentVersion.document_id, DocumentVersion.size)
			.join(latest_ver, and_(
				DocumentVersion.document_id == latest_ver.c.document_id,
				DocumentVersion.created_at == latest_ver.c.max_created,
			))
			.subquery()
		)

		stmt = (
			select(Document, ver_size.c.size)
			.join(Ownership, and_(
				Ownership.resource_id == Document.id,
				Ownership.resource_type == "node",
				Ownership.owner_type == "user",
				Ownership.owner_id == uid,
			))
			.outerjoin(ver_size, ver_size.c.document_id == Document.id)
			.where(Document.deleted_at.is_(None))
			.order_by(desc(Document.updated_at))
			.limit(limit)
		)

		result = await self.session.execute(stmt)
		rows = result.all()

		_EXT_TYPE = {
			'.pdf': 'pdf', '.doc': 'doc', '.docx': 'doc',
			'.xls': 'xls', '.xlsx': 'xls',
			'.jpg': 'img', '.jpeg': 'img', '.png': 'img', '.gif': 'img',
		}

		recent_docs = []
		for doc, size_bytes in rows:
			title = doc.title or 'Untitled'
			ext = '.' + title.rsplit('.', 1)[-1].lower() if '.' in title else ''
			doc_type = _EXT_TYPE.get(ext, 'other')
			recent_docs.append(RecentDocumentOut(
				id=str(doc.id),
				title=title,
				path='/',
				type=doc_type,
				thumbnail_url=None,
				accessed_at=doc.updated_at or doc.created_at,
				access_type='viewed',
				size_bytes=size_bytes or 0,
				page_count=None,
				tags=[],
			))

		return recent_docs

	async def _get_favorites(
		self,
		user_id: str,
		tenant_id: str | None = None,
		limit: int = 10,
	) -> list[FavoriteItemOut]:
		"""Get user's favorite items."""
		stmt = (
			select(UserFavorite)
			.where(UserFavorite.user_id == uuid.UUID(user_id))
			.order_by(desc(UserFavorite.pinned_at))
			.limit(limit)
		)
		result = await self.session.execute(stmt)
		rows = result.scalars().all()

		return [
			FavoriteItemOut(
				id=str(row.id),
				item_type=row.item_type,
				item_id=row.item_id,
				title=row.title,
				path=row.path,
				icon=row.icon,
				pinned_at=row.pinned_at,
			)
			for row in rows
		]

	async def _get_activity_feed(
		self,
		user_id: str,
		tenant_id: str | None = None,
		limit: int = 10,
	) -> list[ActivityEventOut]:
		"""Get activity feed from audit_log for this user, most recent first."""
		AuditLog = _audit_orm()
		uid = uuid.UUID(str(user_id))
		_op_to_type = {
			"insert": "upload",
			"update": "edit",
			"delete": "view",
		}

		stmt = (
			select(AuditLog)
			.where(AuditLog.user_id == uid)
			.order_by(AuditLog.timestamp.desc())
			.limit(limit)
		)
		result = await self.session.execute(stmt)
		rows = result.scalars().all()

		events = []
		for row in rows:
			op = str(row.operation).lower()
			event_type = _op_to_type.get(op, "edit")
			events.append(ActivityEventOut(
				id=str(row.id),
				type=event_type,
				title=f"{event_type.capitalize()} on {row.table_name}",
				description=row.audit_message,
				document_id=str(row.record_id) if row.table_name in ("nodes", "documents") else None,
				actor=ActivityActorOut(
					id=str(row.user_id),
					name=row.username or "unknown",
				) if row.user_id else None,
				timestamp=row.timestamp,
			))
		return events

	async def _get_notifications(
		self,
		user_id: str,
		limit: int = 20,
		unread_only: bool = False,
	) -> list[NotificationOut]:
		"""Get user notifications ordered by created_at DESC."""
		conditions = [UserNotification.user_id == uuid.UUID(user_id)]
		if unread_only:
			conditions.append(UserNotification.is_read == False)  # noqa: E712

		stmt = (
			select(UserNotification)
			.where(and_(*conditions))
			.order_by(desc(UserNotification.created_at))
			.limit(limit)
		)
		result = await self.session.execute(stmt)
		rows = result.scalars().all()

		return [
			NotificationOut(
				id=str(row.id),
				type=row.type,
				title=row.title,
				message=row.message,
				is_read=row.is_read,
				link=row.link,
				created_at=row.created_at,
				metadata=row.notification_metadata,
			)
			for row in rows
		]

	async def _get_calendar_events(
		self,
		user_id: str,
		tenant_id: str | None = None,
	) -> list[CalendarEventOut]:
		"""Get workflow step deadlines assigned to user that fall in the current month."""
		WorkflowStepExecution, WorkflowStep, WorkflowInstance, Workflow, WorkflowApprovalRequest = _workflow_orm()
		uid = uuid.UUID(str(user_id))
		now = datetime.now(timezone.utc)
		month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
		if month_start.month == 12:
			month_end = month_start.replace(year=month_start.year + 1, month=1)
		else:
			month_end = month_start.replace(month=month_start.month + 1)

		stmt = (
			select(WorkflowStepExecution, WorkflowStep.name, WorkflowInstance.workflow_id)
			.join(WorkflowStep, WorkflowStepExecution.step_id == WorkflowStep.id)
			.join(WorkflowInstance, WorkflowStepExecution.instance_id == WorkflowInstance.id)
			.where(
				WorkflowStepExecution.assigned_to == uid,
				WorkflowStepExecution.deadline_at >= month_start,
				WorkflowStepExecution.deadline_at < month_end,
			)
			.order_by(WorkflowStepExecution.deadline_at.asc())
		)
		result = await self.session.execute(stmt)
		rows = result.all()

		return [
			CalendarEventOut(
				id=str(row[0].id),
				title=f"Deadline: {row[1]}",
				type="deadline",
				date=row[0].deadline_at,
				workflow_id=str(row[2]),
			)
			for row in rows
		]

	async def _get_recent_searches(
		self,
		user_id: str,
		limit: int = 10,
	) -> list[RecentSearchOut]:
		"""Get user's recent searches ordered by searched_at DESC."""
		stmt = (
			select(UserSearchHistory)
			.where(UserSearchHistory.user_id == uuid.UUID(user_id))
			.order_by(desc(UserSearchHistory.searched_at))
			.limit(limit)
		)
		result = await self.session.execute(stmt)
		rows = result.scalars().all()

		return [
			RecentSearchOut(
				id=str(row.id),
				query=row.query,
				filters=row.filters,
				result_count=row.result_count,
				searched_at=row.searched_at,
			)
			for row in rows
		]

	# --- Workflow task actions ---

	async def execute_workflow_task_action(
		self,
		task_id: str,
		action_id: str,
		user_id: str,
		comment: str | None = None,
	) -> dict:
		"""Advance a WorkflowStepExecution based on the requested action.

		approve/complete  → completed
		reject            → failed
		forward           → in_progress (stays in queue for re-assignment)
		comment/custom    → no status change; acknowledged
		"""
		from datetime import timezone as _tz
		WorkflowStepExecution, *_ = _workflow_orm()
		uid = uuid.UUID(str(user_id))
		try:
			exe_id = uuid.UUID(task_id)
		except ValueError:
			raise ValueError(f"Invalid task_id: {task_id}")

		stmt = select(WorkflowStepExecution).where(
			WorkflowStepExecution.id == exe_id,
			WorkflowStepExecution.assigned_to == uid,
		)
		result = await self.session.execute(stmt)
		exe = result.scalar_one_or_none()

		if not exe:
			return {"status": "not_found", "task_id": task_id, "action_id": action_id}

		_action_to_status = {
			"approve": "completed",
			"complete": "completed",
			"reject": "failed",
			"forward": "in_progress",
		}
		new_status = _action_to_status.get(action_id)
		if new_status and exe.status != new_status:
			exe.status = new_status
			if new_status in ("completed", "failed"):
				exe.completed_at = datetime.now(_tz.utc)
			if comment:
				exe.result_data = {**(exe.result_data or {}), "comment": comment}
			await self.session.commit()

		return {
			"status": "success",
			"task_id": task_id,
			"action_id": action_id,
			"new_status": exe.status,
		}

	# --- Favorite management ---

	async def add_favorite(
		self,
		user_id: str,
		data: FavoriteItemCreate,
		tenant_id: str | None = None,
	) -> FavoriteItemOut:
		"""Insert a new favorite; return existing row if unique constraint would fire."""
		# Check for existing entry first to give a clean response on duplicate
		existing_stmt = select(UserFavorite).where(
			and_(
				UserFavorite.user_id == uuid.UUID(user_id),
				UserFavorite.item_type == data.item_type,
				UserFavorite.item_id == data.item_id,
			)
		)
		existing_result = await self.session.execute(existing_stmt)
		existing = existing_result.scalar_one_or_none()

		if existing:
			return FavoriteItemOut(
				id=str(existing.id),
				item_type=existing.item_type,
				item_id=existing.item_id,
				title=existing.title,
				path=existing.path,
				icon=existing.icon,
				pinned_at=existing.pinned_at,
			)

		row = UserFavorite(
			id=uuid.uuid4(),
			user_id=uuid.UUID(user_id),
			tenant_id=tenant_id,
			item_type=data.item_type,
			item_id=data.item_id,
			title=data.title,
			path=data.path,
			icon=None,
			pinned_at=_utcnow(),
		)
		self.session.add(row)
		await self.session.flush()

		return FavoriteItemOut(
			id=str(row.id),
			item_type=row.item_type,
			item_id=row.item_id,
			title=row.title,
			path=row.path,
			icon=row.icon,
			pinned_at=row.pinned_at,
		)

	async def remove_favorite(
		self,
		user_id: str,
		favorite_id: str,
	) -> bool:
		"""Delete a favorite by id; return True if deleted, False if not found."""
		stmt = delete(UserFavorite).where(
			and_(
				UserFavorite.id == uuid.UUID(favorite_id),
				UserFavorite.user_id == uuid.UUID(user_id),
			)
		)
		result = await self.session.execute(stmt)
		await self.session.flush()
		return result.rowcount > 0

	# --- Notification management ---

	async def mark_notification_read(
		self,
		user_id: str,
		notification_id: str,
	) -> bool:
		"""Mark a single notification as read. Returns True if it existed."""
		now = _utcnow()
		stmt = (
			update(UserNotification)
			.where(
				and_(
					UserNotification.id == uuid.UUID(notification_id),
					UserNotification.user_id == uuid.UUID(user_id),
				)
			)
			.values(is_read=True, read_at=now)
		)
		result = await self.session.execute(stmt)
		await self.session.flush()
		return result.rowcount > 0

	async def mark_all_notifications_read(self, user_id: str) -> int:
		"""Mark all unread notifications as read. Returns count updated."""
		now = _utcnow()
		stmt = (
			update(UserNotification)
			.where(
				and_(
					UserNotification.user_id == uuid.UUID(user_id),
					UserNotification.is_read == False,  # noqa: E712
				)
			)
			.values(is_read=True, read_at=now)
		)
		result = await self.session.execute(stmt)
		await self.session.flush()
		return result.rowcount

	# --- Search history management ---

	async def clear_search_history(self, user_id: str) -> int:
		"""Delete all search history for a user. Returns count deleted."""
		stmt = delete(UserSearchHistory).where(
			UserSearchHistory.user_id == uuid.UUID(user_id)
		)
		result = await self.session.execute(stmt)
		await self.session.flush()
		return result.rowcount

	async def record_search(
		self,
		user_id: str,
		query: str,
		filters: dict | None = None,
		result_count: int = 0,
	) -> RecentSearchOut:
		"""Persist a search query to history."""
		row = UserSearchHistory(
			id=uuid.uuid4(),
			user_id=uuid.UUID(user_id),
			query=query,
			filters=filters,
			result_count=result_count,
			searched_at=_utcnow(),
		)
		self.session.add(row)
		await self.session.flush()

		return RecentSearchOut(
			id=str(row.id),
			query=row.query,
			filters=row.filters,
			result_count=row.result_count,
			searched_at=row.searched_at,
		)


async def get_user_home_service(session: AsyncSession) -> UserHomeService:
	"""Get user home service instance."""
	return UserHomeService(session)
