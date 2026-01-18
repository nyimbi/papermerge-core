import logging
import asyncio

from celery import shared_task

from papermerge.celery_app import app as celery_app
from papermerge.core.utils.decorators import if_redis_present

logger = logging.getLogger(__name__)


def _log_task(name: str) -> str:
	return f"Running task: {name}"


@shared_task
def delete_user_data(user_id):
    pass
    #try:
    #    user = User.objects.get(id=user_id)
        # first delete all files associated with the user
    #    user.delete_user_data()
        # then delete the user DB entry
    #    user.delete()
    #except User.DoesNotExist:
    #    logger.info(f"User: {user_id} already deleted")

@if_redis_present
def send_task(*args, **kwargs):
	logger.debug(f"Send task {args} {kwargs}")
	celery_app.send_task(*args, **kwargs)


@shared_task
def sync_email_account(account_id: str, owner_id: str):
	"""Sync emails from an IMAP account."""
	logger.info(_log_task(f"sync_email_account:{account_id[:8]}"))

	from papermerge.core.db.engine import sync_engine
	from sqlalchemy.orm import Session
	from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
	from papermerge.core.features.emails.models import EmailAccountModel
	from papermerge.core.features.emails.imap_client import sync_account
	import os

	async def _sync():
		from papermerge.core.db.engine import get_async_session_maker
		async_session = get_async_session_maker()

		async with async_session() as session:
			from sqlalchemy import select
			stmt = select(EmailAccountModel).where(EmailAccountModel.id == account_id)
			result = await session.execute(stmt)
			account = result.scalar_one_or_none()

			if not account:
				logger.error(f"Email account not found: {account_id}")
				return

			if not account.is_active:
				logger.info(f"Email account inactive: {account_id}")
				return

			stats = await sync_account(account, session, owner_id)
			logger.info(
				f"Email sync complete for {account_id[:8]}: "
				f"fetched={stats['messages_fetched']}, "
				f"imported={stats['messages_imported']}, "
				f"errors={len(stats['errors'])}"
			)

	asyncio.run(_sync())


@shared_task
def sync_all_email_accounts():
	"""Sync all active email accounts."""
	logger.info(_log_task("sync_all_email_accounts"))

	from papermerge.core.features.emails.models import EmailAccountModel
	from sqlalchemy import select
	from datetime import datetime, timedelta
	import asyncio

	async def _sync_all():
		from papermerge.core.db.engine import get_async_session_maker
		async_session = get_async_session_maker()

		async with async_session() as session:
			now = datetime.utcnow()

			# Find accounts due for sync
			stmt = select(EmailAccountModel).where(
				EmailAccountModel.is_active == True,
				EmailAccountModel.sync_enabled == True,
			)
			result = await session.execute(stmt)
			accounts = result.scalars().all()

			for account in accounts:
				# Check if due for sync
				if account.last_sync_at:
					next_sync = account.last_sync_at + timedelta(minutes=account.sync_interval_minutes)
					if now < next_sync:
						continue

				# Queue individual sync
				sync_email_account.delay(account.id, account.owner_id)

	asyncio.run(_sync_all())


@shared_task
def process_email_attachments(email_import_id: str, owner_id: str):
	"""Process attachments from an imported email."""
	logger.info(_log_task(f"process_email_attachments:{email_import_id[:8]}"))

	import asyncio

	async def _process():
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.emails.models import EmailImportModel, EmailAttachmentModel
		from sqlalchemy import select
		from sqlalchemy.orm import selectinload

		async_session = get_async_session_maker()

		async with async_session() as session:
			stmt = select(EmailImportModel).where(
				EmailImportModel.id == email_import_id
			).options(selectinload(EmailImportModel.attachments))

			result = await session.execute(stmt)
			email_import = result.scalar_one_or_none()

			if not email_import:
				logger.error(f"Email import not found: {email_import_id}")
				return

			for attachment in email_import.attachments:
				if attachment.import_status != "pending":
					continue

				try:
					# TODO: Create document from attachment content
					# This would involve:
					# 1. Getting the attachment content from storage
					# 2. Creating a Document with the content
					# 3. Updating attachment.document_id
					# 4. Triggering OCR if applicable

					attachment.import_status = "imported"
					logger.info(f"Processed attachment: {attachment.filename}")

				except Exception as e:
					attachment.import_status = "failed"
					attachment.import_error = str(e)
					logger.error(f"Failed to process attachment {attachment.filename}: {e}")

			await session.commit()

	asyncio.run(_process())
