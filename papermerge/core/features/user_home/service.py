# User Home Page Service
import logging
import uuid
from datetime import datetime, timedelta, timezone

from papermerge.core.utils.uuid_compat import uuid7str

from sqlalchemy import select, func, delete, update, desc, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.models import User, Document
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
	)
	return WorkflowStepExecution, WorkflowStep, WorkflowInstance, Workflow

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

		doc_stmt = select(func.count(Document.id)).where(
			Document.created_at >= week_ago
		)
		if tenant_id:
			doc_stmt = doc_stmt.where(Document.tenant_id == tenant_id)
		result = await self.session.execute(doc_stmt)
		docs_this_week = result.scalar() or 0

		# Count unread notifications as a proxy for pending tasks
		unread_stmt = select(func.count(UserNotification.id)).where(
			and_(
				UserNotification.user_id == uuid.UUID(user_id),
				UserNotification.is_read == False,  # noqa: E712
			)
		)
		unread_result = await self.session.execute(unread_stmt)
		unread_count = unread_result.scalar() or 0

		return UserStats(
			pending_tasks=0,
			documents_this_week=docs_this_week,
			approvals_pending=0,
			deadlines_upcoming=unread_count,
		)

	async def _get_workflow_tasks(
		self,
		user_id: str,
		tenant_id: str | None = None,
		limit: int = 10,
	) -> list[WorkflowTaskOut]:
		"""Get pending workflow tasks assigned to user from workflow_step_executions."""
		WorkflowStepExecution, WorkflowStep, WorkflowInstance, Workflow = _workflow_orm()
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
		"""Get recently accessed documents."""
		stmt = select(Document).where(
			Document.user_id == user_id
		).order_by(desc(Document.updated_at)).limit(limit)

		if tenant_id:
			stmt = stmt.where(Document.tenant_id == tenant_id)

		result = await self.session.execute(stmt)
		documents = result.scalars().all()

		recent_docs = []
		for doc in documents:
			title = doc.title or 'Untitled'
			doc_type = 'other'
			lower = title.lower()
			if lower.endswith('.pdf'):
				doc_type = 'pdf'
			elif lower.endswith(('.doc', '.docx')):
				doc_type = 'doc'
			elif lower.endswith(('.xls', '.xlsx')):
				doc_type = 'xls'
			elif lower.endswith(('.jpg', '.jpeg', '.png', '.gif')):
				doc_type = 'img'

			recent_docs.append(RecentDocumentOut(
				id=str(doc.id),
				title=title,
				path='/',
				type=doc_type,
				thumbnail_url=None,
				accessed_at=doc.updated_at or doc.created_at,
				access_type='viewed',
				size_bytes=0,
				page_count=getattr(doc, 'page_count', None),
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
		WorkflowStepExecution, WorkflowStep, WorkflowInstance, Workflow = _workflow_orm()
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
