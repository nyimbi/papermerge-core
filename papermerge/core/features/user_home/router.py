# User Home Page Router
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db import get_session
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.auth.schema import User

from .service import UserHomeService
from .views import (
	UserHomeDataOut, WorkflowTaskOut, RecentDocumentOut, FavoriteItemOut,
	NotificationOut, CalendarEventOut, RecentSearchOut, FavoriteItemCreate,
	TaskActionRequest,
)

router = APIRouter(tags=["User Home"])


async def get_service(session: Annotated[AsyncSession, Depends(get_session)]) -> UserHomeService:
	return UserHomeService(session)


# --- Home Page Data ---

@router.get("/users/me/home", response_model=UserHomeDataOut)
async def get_user_home(
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get aggregated home page data for current user."""
	return await service.get_user_home_data(
		user_id=user.id,
		tenant_id=user.tenant_id,
	)


# --- Workflow Tasks ---

@router.get("/workflows/tasks/assigned", response_model=list[WorkflowTaskOut])
async def get_assigned_tasks(
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
	status: str | None = Query(None),
	limit: int = Query(20, ge=1, le=100),
):
	"""Get workflow tasks assigned to current user."""
	return await service._get_workflow_tasks(
		user_id=user.id,
		tenant_id=user.tenant_id,
		limit=limit,
	)


@router.post("/workflows/tasks/{task_id}/action")
async def execute_task_action(
	task_id: str,
	data: TaskActionRequest,
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Execute an action on a workflow task."""
	# Would delegate to workflow service
	return {"status": "success", "task_id": task_id, "action_id": data.action_id}


# --- Recent Documents ---

@router.get("/documents/recent", response_model=list[RecentDocumentOut])
async def get_recent_documents(
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
	limit: int = Query(20, ge=1, le=100),
	type: str | None = Query(None),
):
	"""Get recently accessed documents."""
	return await service._get_recent_documents(
		user_id=user.id,
		tenant_id=user.tenant_id,
		limit=limit,
	)


# --- Favorites ---

@router.get("/users/me/favorites", response_model=list[FavoriteItemOut])
async def get_favorites(
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get current user's favorite items."""
	return await service._get_favorites(
		user_id=user.id,
		tenant_id=user.tenant_id,
	)


@router.post("/users/me/favorites", response_model=FavoriteItemOut, status_code=201)
async def add_favorite(
	data: FavoriteItemCreate,
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Add an item to favorites."""
	return await service.add_favorite(
		user_id=user.id,
		data=data,
		tenant_id=user.tenant_id,
	)


@router.delete("/users/me/favorites/{favorite_id}", status_code=204)
async def remove_favorite(
	favorite_id: str,
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Remove an item from favorites."""
	removed = await service.remove_favorite(user.id, favorite_id)
	if not removed:
		raise HTTPException(status_code=404, detail="Favorite not found")


# --- Notifications ---

@router.get("/notifications", response_model=list[NotificationOut])
async def get_notifications(
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
	unread_only: bool = Query(False),
	limit: int = Query(50, ge=1, le=100),
):
	"""Get user notifications."""
	return await service._get_notifications(
		user_id=user.id,
		limit=limit,
	)


@router.post("/notifications/{notification_id}/read", status_code=204)
async def mark_notification_read(
	notification_id: str,
	user: Annotated[User, Depends(get_current_user)],
):
	"""Mark a notification as read."""
	# Would update notification in database
	pass


@router.post("/notifications/read-all", status_code=204)
async def mark_all_notifications_read(
	user: Annotated[User, Depends(get_current_user)],
):
	"""Mark all notifications as read."""
	# Would update all user notifications
	pass


# --- Calendar ---

@router.get("/calendar/events", response_model=list[CalendarEventOut])
async def get_calendar_events(
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
	from_date: str | None = Query(None, alias="from"),
	to_date: str | None = Query(None, alias="to"),
):
	"""Get calendar events for date range."""
	return await service._get_calendar_events(
		user_id=user.id,
		tenant_id=user.tenant_id,
	)


# --- Search History ---

@router.get("/search/recent", response_model=list[RecentSearchOut])
async def get_recent_searches(
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
	limit: int = Query(10, ge=1, le=50),
):
	"""Get user's recent searches."""
	return await service._get_recent_searches(
		user_id=user.id,
		limit=limit,
	)


@router.delete("/search/recent", status_code=204)
async def clear_recent_searches(
	user: Annotated[User, Depends(get_current_user)],
):
	"""Clear user's recent search history."""
	# Would delete from search history table
	pass


# --- Activity ---

@router.get("/activity")
async def get_activity_feed(
	service: Annotated[UserHomeService, Depends(get_service)],
	user: Annotated[User, Depends(get_current_user)],
	limit: int = Query(20, ge=1, le=100),
	types: str | None = Query(None),
):
	"""Get activity feed."""
	return await service._get_activity_feed(
		user_id=user.id,
		tenant_id=user.tenant_id,
		limit=limit,
	)
