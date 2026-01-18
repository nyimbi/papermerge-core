# User Home Page Service
import logging
from datetime import datetime, timedelta
from uuid_extensions import uuid7str

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.models import User, Document, Folder, Tag
from .views import (
	UserHomeDataOut, UserInfo, UserStats, WorkflowTaskOut, TaskAction,
	RecentDocumentOut, FavoriteItemOut, ActivityEventOut, NotificationOut,
	CalendarEventOut, RecentSearchOut, FavoriteItemCreate, DocumentTag,
	ActivityActorOut, TaskActor,
)

logger = logging.getLogger(__name__)


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
		# Get user info
		user_info = await self._get_user_info(user_id)

		# Get all data in parallel-ish manner
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

		# Build display name
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
		# Get counts from various tables
		# For now, return placeholder data
		# In production, these would query actual workflow, document, and deadline tables

		now = datetime.utcnow()
		week_ago = now - timedelta(days=7)

		# Count recent documents
		doc_stmt = select(func.count(Document.id)).where(
			Document.created_at >= week_ago
		)
		if tenant_id:
			doc_stmt = doc_stmt.where(Document.tenant_id == tenant_id)
		result = await self.session.execute(doc_stmt)
		docs_this_week = result.scalar() or 0

		return UserStats(
			pending_tasks=0,  # Would come from workflow tasks table
			documents_this_week=docs_this_week,
			approvals_pending=0,  # Would come from workflow approval queue
			deadlines_upcoming=0,  # Would come from calendar/deadline table
		)

	async def _get_workflow_tasks(
		self,
		user_id: str,
		tenant_id: str | None = None,
		limit: int = 10,
	) -> list[WorkflowTaskOut]:
		"""Get pending workflow tasks for user."""
		# This would query the workflow tasks table
		# For now, return empty list
		# In production:
		# - Query WorkflowTask where assigned_to = user_id and status in ('pending', 'in_progress')
		# - Join with Workflow for workflow_name
		# - Join with Document for document_title
		# - Order by priority, due_date

		return []

	async def _get_recent_documents(
		self,
		user_id: str,
		tenant_id: str | None = None,
		limit: int = 10,
	) -> list[RecentDocumentOut]:
		"""Get recently accessed documents."""
		# Query DocumentAccess or AuditLog to get recent document accesses
		# For now, get most recently created/updated documents

		stmt = select(Document).where(
			Document.user_id == user_id
		).order_by(desc(Document.updated_at)).limit(limit)

		if tenant_id:
			stmt = stmt.where(Document.tenant_id == tenant_id)

		result = await self.session.execute(stmt)
		documents = result.scalars().all()

		recent_docs = []
		for doc in documents:
			# Determine file type from title/extension
			title = doc.title or 'Untitled'
			doc_type = 'other'
			if title.lower().endswith('.pdf'):
				doc_type = 'pdf'
			elif title.lower().endswith(('.doc', '.docx')):
				doc_type = 'doc'
			elif title.lower().endswith(('.xls', '.xlsx')):
				doc_type = 'xls'
			elif title.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
				doc_type = 'img'

			recent_docs.append(RecentDocumentOut(
				id=str(doc.id),
				title=title,
				path='/',  # Would compute full path
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
		# Would query a UserFavorites table
		# For now, return empty list

		return []

	async def _get_activity_feed(
		self,
		user_id: str,
		tenant_id: str | None = None,
		limit: int = 10,
	) -> list[ActivityEventOut]:
		"""Get activity feed for user."""
		# Would query AuditLog or ActivityLog table
		# For now, return empty list

		return []

	async def _get_notifications(
		self,
		user_id: str,
		limit: int = 20,
	) -> list[NotificationOut]:
		"""Get user notifications."""
		# Would query Notifications table
		# For now, return empty list

		return []

	async def _get_calendar_events(
		self,
		user_id: str,
		tenant_id: str | None = None,
	) -> list[CalendarEventOut]:
		"""Get calendar events for current month."""
		# Would query CalendarEvents or Deadlines table
		# For now, return empty list

		return []

	async def _get_recent_searches(
		self,
		user_id: str,
		limit: int = 10,
	) -> list[RecentSearchOut]:
		"""Get user's recent searches."""
		# Would query SearchHistory table
		# For now, return empty list

		return []

	# Favorite management
	async def add_favorite(
		self,
		user_id: str,
		data: FavoriteItemCreate,
		tenant_id: str | None = None,
	) -> FavoriteItemOut:
		"""Add an item to favorites."""
		# Would insert into UserFavorites table
		# For now, return the created item

		return FavoriteItemOut(
			id=uuid7str(),
			item_type=data.item_type,
			item_id=data.item_id,
			title=data.title,
			path=data.path,
			icon=None,
			pinned_at=datetime.utcnow(),
		)

	async def remove_favorite(
		self,
		user_id: str,
		favorite_id: str,
	) -> bool:
		"""Remove an item from favorites."""
		# Would delete from UserFavorites table
		return True


async def get_user_home_service(session: AsyncSession) -> UserHomeService:
	"""Get user home service instance."""
	return UserHomeService(session)
