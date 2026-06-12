from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import schema
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.notifications.db import api as dbapi
from papermerge.core.features.notifications.schema import NotificationOut

router = APIRouter(
	prefix="/notifications",
	tags=["notifications"],
)


def _serialize(n) -> NotificationOut:
	return NotificationOut(
		id=n.id,
		type=n.type,
		title=n.title,
		message=n.message,
		timestamp=n.created_at.isoformat(),
		read=n.read,
		link=n.link,
		metadata=n.extra,
	)


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
	unread_only: bool = False,
	limit: int = 50,
) -> list[NotificationOut]:
	"""List notifications for the current user."""
	notifications = await dbapi.get_notifications(
		session=db_session,
		user_id=current_user.id,
		unread_only=unread_only,
		limit=limit,
	)
	return [_serialize(n) for n in notifications]


@router.get("/count")
async def get_unread_count(
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Return count of unread notifications."""
	count = await dbapi.get_unread_count(
		session=db_session,
		user_id=current_user.id,
	)
	return {"unread_count": count}


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read(
	notification_id: str,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> NotificationOut:
	"""Mark a single notification as read."""
	updated = await dbapi.mark_as_read(
		session=db_session,
		notification_id=notification_id,
		user_id=current_user.id,
	)
	if not updated:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Notification not found",
		)
	# Fetch the updated record to return
	notifications = await dbapi.get_notifications(
		session=db_session,
		user_id=current_user.id,
		limit=1000,
	)
	match = next((n for n in notifications if n.id == notification_id), None)
	if match is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Notification not found",
		)
	return _serialize(match)


@router.post("/read-all")
async def mark_all_read(
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Mark all notifications as read."""
	updated = await dbapi.mark_all_as_read(
		session=db_session,
		user_id=current_user.id,
	)
	return {"updated": updated}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_notification(
	notification_id: str,
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Dismiss (delete) a single notification."""
	deleted = await dbapi.delete_notification(
		session=db_session,
		notification_id=notification_id,
		user_id=current_user.id,
	)
	if not deleted:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Notification not found",
		)


@router.post("/clear-all")
async def clear_all(
	current_user: Annotated[schema.User, Depends(get_current_user)],
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Clear all notifications for the current user."""
	deleted = await dbapi.clear_all_notifications(
		session=db_session,
		user_id=current_user.id,
	)
	return {"deleted": deleted}
