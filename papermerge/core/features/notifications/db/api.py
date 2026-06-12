from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.notifications.db.orm import Notification
from papermerge.core.features.notifications.schema import NotificationCreate


async def get_notifications(
	session: AsyncSession,
	user_id: UUID,
	unread_only: bool = False,
	limit: int = 50,
) -> list[Notification]:
	stmt = (
		select(Notification)
		.where(Notification.user_id == user_id)
	)
	if unread_only:
		stmt = stmt.where(Notification.read == False)  # noqa: E712
	stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
	result = await session.execute(stmt)
	return list(result.scalars().all())


async def get_unread_count(session: AsyncSession, user_id: UUID) -> int:
	stmt = (
		select(func.count())
		.select_from(Notification)
		.where(Notification.user_id == user_id, Notification.read == False)  # noqa: E712
	)
	result = await session.execute(stmt)
	return result.scalar() or 0


async def mark_as_read(
	session: AsyncSession,
	notification_id: str,
	user_id: UUID,
) -> bool:
	stmt = (
		update(Notification)
		.where(
			Notification.id == notification_id,
			Notification.user_id == user_id,
		)
		.values(read=True)
	)
	result = await session.execute(stmt)
	await session.commit()
	return result.rowcount > 0


async def mark_all_as_read(session: AsyncSession, user_id: UUID) -> int:
	stmt = (
		update(Notification)
		.where(
			Notification.user_id == user_id,
			Notification.read == False,  # noqa: E712
		)
		.values(read=True)
	)
	result = await session.execute(stmt)
	await session.commit()
	return result.rowcount


async def delete_notification(
	session: AsyncSession,
	notification_id: str,
	user_id: UUID,
) -> bool:
	stmt = delete(Notification).where(
		Notification.id == notification_id,
		Notification.user_id == user_id,
	)
	result = await session.execute(stmt)
	await session.commit()
	return result.rowcount > 0


async def clear_all_notifications(session: AsyncSession, user_id: UUID) -> int:
	stmt = delete(Notification).where(Notification.user_id == user_id)
	result = await session.execute(stmt)
	await session.commit()
	return result.rowcount


async def create_notification(
	session: AsyncSession,
	data: NotificationCreate,
) -> Notification:
	notification = Notification(
		user_id=UUID(data.user_id),
		type=data.type,
		title=data.title,
		message=data.message,
		link=data.link,
		extra=data.metadata,
	)
	session.add(notification)
	await session.commit()
	await session.refresh(notification)
	return notification
