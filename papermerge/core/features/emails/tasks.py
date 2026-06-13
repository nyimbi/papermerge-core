# (c) Copyright Datacraft, 2026
"""
Celery tasks for email polling.

Feature-local task module. The canonical shared_task implementations live in
papermerge.core.tasks; this module exposes a clean feature-scoped interface and
adds the poll_* wrappers that the task spec requires.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)


def _log_task(name: str) -> str:
	return f"email.task: {name}"


# ---------------------------------------------------------------------------
# Core polling helpers (async, called by sync Celery tasks via asyncio.run)
# ---------------------------------------------------------------------------

async def _poll_email_account(account_id: str) -> dict:
	"""
	Poll one email account for new messages and import them.

	Steps:
	  1. Load EmailAccountModel from DB
	  2. Bail if account is inactive or sync is disabled
	  3. Delegate to imap_client.sync_account which handles connect/fetch/import
	  4. Update account.last_sync_at and persist errors

	Returns stats dict: {imported: N, errors: N, fetched: N}
	"""
	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.features.emails.models import EmailAccountModel
	from papermerge.core.features.emails.imap_client import sync_account
	from sqlalchemy import select

	async_session = get_async_session_maker()

	async with async_session() as session:
		stmt = select(EmailAccountModel).where(EmailAccountModel.id == account_id)
		result = await session.execute(stmt)
		account = result.scalar_one_or_none()

		if not account:
			logger.error(f"Email account not found: {account_id}")
			return {"imported": 0, "errors": 1, "fetched": 0, "error_detail": "Account not found"}

		if not account.is_active:
			logger.info(f"Email account inactive, skipping: {account_id[:8]}")
			return {"imported": 0, "errors": 0, "fetched": 0, "skipped": True}

		if not account.sync_enabled:
			logger.info(f"Email sync disabled for account: {account_id[:8]}")
			return {"imported": 0, "errors": 0, "fetched": 0, "skipped": True}

		try:
			stats = await sync_account(account, session, account.owner_id)

			# Persist error state if any
			if stats["errors"]:
				account.connection_status = "error"
				account.connection_error = "; ".join(str(e) for e in stats["errors"][:3])
			else:
				account.connection_status = "connected"
				account.connection_error = None

			await session.commit()

			logger.info(
				f"Poll complete for {account_id[:8]}: "
				f"fetched={stats['messages_fetched']}, "
				f"imported={stats['messages_imported']}, "
				f"errors={len(stats['errors'])}"
			)

			return {
				"imported": stats["messages_imported"],
				"errors": len(stats["errors"]),
				"fetched": stats["messages_fetched"],
				"skipped": stats["messages_skipped"],
				"error_details": stats["errors"],
			}

		except Exception as e:
			logger.error(f"Unexpected error polling account {account_id[:8]}: {e}")
			try:
				account.connection_status = "error"
				account.connection_error = str(e)
				await session.commit()
			except Exception:
				pass
			return {"imported": 0, "errors": 1, "fetched": 0, "error_detail": str(e)}


# ---------------------------------------------------------------------------
# Celery shared tasks
# ---------------------------------------------------------------------------

@shared_task(
	bind=True,
	max_retries=3,
	default_retry_delay=60,
	name="darchiva.email.poll_account",
)
def poll_email_account(self, account_id: str) -> dict:
	"""
	Poll one email account for new messages and import them.

	Retries up to 3 times on failure with 60s delay.
	Returns stats: {imported: N, errors: N, fetched: N}
	"""
	logger.info(_log_task(f"poll_email_account:{account_id[:8]}"))

	try:
		return asyncio.run(_poll_email_account(account_id))
	except Exception as exc:
		logger.warning(
			f"poll_email_account failed for {account_id[:8]}, "
			f"retry {self.request.retries}/{self.max_retries}: {exc}"
		)
		raise self.retry(exc=exc)


@shared_task(name="darchiva.email.poll_all_accounts")
def poll_all_active_email_accounts() -> dict:
	"""
	Poll all active email accounts that are due for sync.

	Called by Celery beat every 5 minutes. Fans out to poll_email_account.delay
	for each account whose sync interval has elapsed.

	Returns {queued: N, skipped: N}.
	"""
	logger.info(_log_task("poll_all_active_email_accounts"))

	async def _find_due_accounts() -> list[tuple[str, str]]:
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.emails.models import EmailAccountModel
		from sqlalchemy import select

		async_session = get_async_session_maker()
		now = datetime.utcnow()

		async with async_session() as session:
			stmt = select(EmailAccountModel).where(
				EmailAccountModel.is_active == True,
				EmailAccountModel.sync_enabled == True,
			)
			result = await session.execute(stmt)
			accounts = result.scalars().all()

			due = []
			for account in accounts:
				if account.last_sync_at:
					next_sync = account.last_sync_at + timedelta(
						minutes=account.sync_interval_minutes
					)
					if now < next_sync:
						continue
				due.append((account.id, account.owner_id))

			return due

	due_accounts = asyncio.run(_find_due_accounts())

	queued = 0
	for account_id, _owner_id in due_accounts:
		poll_email_account.delay(account_id)
		queued += 1

	skipped = 0  # accounts not yet due are simply not in due_accounts
	logger.info(f"poll_all_active_email_accounts: queued={queued}")

	return {"queued": queued, "skipped": skipped}


# ---------------------------------------------------------------------------
# Aliases matching the original core/tasks.py names so callers continue to
# work whether they import from here or from papermerge.core.tasks.
# ---------------------------------------------------------------------------

# Re-export the older task names as aliases for backward compatibility.
# The core tasks module registers these under different Celery task names,
# so we just point the Python names at the same underlying function.
try:
	from papermerge.core.tasks import (
		sync_email_account,
		sync_all_email_accounts,
		process_email_attachments,
	)
except ImportError:
	# Graceful degradation if running outside the full app context
	sync_email_account = None
	sync_all_email_accounts = None
	process_email_attachments = None
