# (c) Copyright Datacraft, 2026
"""
IMAP client for email synchronization.

Provides async IMAP operations for fetching emails from mailboxes.
"""
import asyncio
import logging
import imaplib
import ssl
from datetime import datetime
from email import message_from_bytes
from email.policy import default as default_policy
from typing import Any

from .models import EmailAccountModel
from .parser import EmailParser

logger = logging.getLogger(__name__)


def _log_imap(action: str, account: str) -> str:
	return f"IMAP {action}: {account}"


class IMAPClient:
	"""
	Async IMAP client wrapper.

	Uses imaplib with asyncio.to_thread for non-blocking operations.
	"""

	def __init__(self, account: EmailAccountModel):
		self.account = account
		self._client: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None
		self._parser = EmailParser(include_attachments=True)

	async def connect(self) -> bool:
		"""Connect to IMAP server."""
		from papermerge.core.security import decrypt_secret

		logger.info(_log_imap("connecting", self.account.email_address))

		try:
			if self.account.imap_use_ssl:
				ctx = ssl.create_default_context()
				self._client = await asyncio.to_thread(
					imaplib.IMAP4_SSL,
					self.account.imap_host,
					self.account.imap_port or 993,
					ssl_context=ctx,
				)
			else:
				self._client = await asyncio.to_thread(
					imaplib.IMAP4,
					self.account.imap_host,
					self.account.imap_port or 143,
				)

			# Login
			username = self.account.imap_username or self.account.email_address
			password = decrypt_secret(self.account.imap_password_encrypted) if self.account.imap_password_encrypted else ""

			await asyncio.to_thread(
				self._client.login,
				username,
				password,
			)

			logger.info(_log_imap("connected", self.account.email_address))
			return True

		except Exception as e:
			logger.error(f"IMAP connection failed: {e}")
			return False

	async def disconnect(self) -> None:
		"""Disconnect from IMAP server."""
		if self._client:
			try:
				await asyncio.to_thread(self._client.logout)
			except Exception:
				pass
			self._client = None

	async def list_folders(self) -> list[str]:
		"""List available folders."""
		if not self._client:
			return []

		result, data = await asyncio.to_thread(self._client.list)

		folders = []
		if result == "OK":
			for item in data:
				if item:
					# Parse folder name from IMAP response
					parts = item.decode().split(' "/" ')
					if len(parts) >= 2:
						folder = parts[-1].strip('"')
						folders.append(folder)

		return folders

	async def select_folder(self, folder: str = "INBOX") -> tuple[bool, int]:
		"""Select a folder and return message count."""
		if not self._client:
			return False, 0

		try:
			result, data = await asyncio.to_thread(self._client.select, folder)
			if result == "OK":
				count = int(data[0].decode())
				return True, count
			return False, 0
		except Exception as e:
			logger.error(f"Failed to select folder {folder}: {e}")
			return False, 0

	async def search_messages(
		self,
		criteria: str = "ALL",
		since_date: datetime | None = None,
		since_uid: str | None = None,
	) -> list[str]:
		"""Search for messages matching criteria."""
		if not self._client:
			return []

		search_parts = []

		if since_date:
			date_str = since_date.strftime("%d-%b-%Y")
			search_parts.append(f'SINCE "{date_str}"')

		if since_uid:
			search_parts.append(f"UID {since_uid}:*")

		if criteria != "ALL":
			search_parts.append(criteria)

		search_str = " ".join(search_parts) if search_parts else "ALL"

		try:
			result, data = await asyncio.to_thread(
				self._client.search,
				None,
				search_str,
			)

			if result == "OK" and data[0]:
				return data[0].decode().split()
			return []

		except Exception as e:
			logger.error(f"IMAP search failed: {e}")
			return []

	async def fetch_message(self, msg_id: str) -> bytes | None:
		"""Fetch a single message by ID."""
		if not self._client:
			return None

		try:
			result, data = await asyncio.to_thread(
				self._client.fetch,
				msg_id,
				"(RFC822)",
			)

			if result == "OK" and data[0]:
				# data[0] is tuple (response_part, message_bytes)
				if isinstance(data[0], tuple):
					return data[0][1]

			return None

		except Exception as e:
			logger.error(f"Failed to fetch message {msg_id}: {e}")
			return None

	async def fetch_messages(
		self,
		msg_ids: list[str],
		batch_size: int = 50,
	) -> list[bytes]:
		"""Fetch multiple messages in batches."""
		messages = []

		for i in range(0, len(msg_ids), batch_size):
			batch = msg_ids[i:i + batch_size]
			id_set = ",".join(batch)

			try:
				result, data = await asyncio.to_thread(
					self._client.fetch,
					id_set,
					"(RFC822)",
				)

				if result == "OK":
					for item in data:
						if isinstance(item, tuple) and len(item) >= 2:
							messages.append(item[1])

			except Exception as e:
				logger.error(f"Failed to fetch batch: {e}")

		return messages

	async def get_uid(self, msg_id: str) -> str | None:
		"""Get UID for a message."""
		if not self._client:
			return None

		try:
			result, data = await asyncio.to_thread(
				self._client.fetch,
				msg_id,
				"(UID)",
			)

			if result == "OK" and data[0]:
				# Parse UID from response
				response = data[0].decode() if isinstance(data[0], bytes) else str(data[0])
				if "UID" in response:
					uid = response.split("UID")[1].split(")")[0].strip()
					return uid

			return None

		except Exception as e:
			logger.error(f"Failed to get UID: {e}")
			return None


async def test_imap_connection(account: EmailAccountModel) -> tuple[bool, str]:
	"""Test IMAP connection for an account."""
	client = IMAPClient(account)

	try:
		if await client.connect():
			folders = await client.list_folders()
			await client.disconnect()
			return True, f"Connected successfully. Found {len(folders)} folders."
		return False, "Connection failed"

	except Exception as e:
		return False, str(e)

	finally:
		await client.disconnect()


async def sync_account(
	account: EmailAccountModel,
	session,  # AsyncSession
	owner_id: str,
	max_messages: int = 100,
) -> dict[str, Any]:
	"""
	Synchronize emails from an IMAP account.

	Returns sync statistics.
	"""
	from .service import import_email, get_email_import_by_message_id
	from .views import EmailImportCreate, EmailSource
	from datetime import datetime

	stats = {
		"messages_fetched": 0,
		"messages_imported": 0,
		"messages_skipped": 0,
		"errors": [],
	}

	client = IMAPClient(account)

	try:
		if not await client.connect():
			stats["errors"].append("Connection failed")
			return stats

		folders = account.sync_folders or ["INBOX"]
		parser = EmailParser(include_attachments=account.import_attachments)

		for folder in folders:
			ok, count = await client.select_folder(folder)
			if not ok:
				stats["errors"].append(f"Failed to select folder: {folder}")
				continue

			# Search for messages
			msg_ids = await client.search_messages(
				since_date=account.sync_since_date,
				since_uid=account.last_sync_uid,
			)

			# Limit to max_messages
			msg_ids = msg_ids[-max_messages:] if len(msg_ids) > max_messages else msg_ids

			for msg_id in msg_ids:
				try:
					raw_message = await client.fetch_message(msg_id)
					if not raw_message:
						continue

					stats["messages_fetched"] += 1

					# Parse
					parsed = parser.parse_bytes(raw_message)

					# Check if already imported
					existing = await get_email_import_by_message_id(session, parsed.message_id)
					if existing:
						stats["messages_skipped"] += 1
						continue

					# Import
					options = EmailImportCreate(
						source=EmailSource.IMAP,
						source_account_id=account.id,
						folder_id=account.target_folder_id,
						import_attachments=account.import_attachments,
						attachment_filter=account.attachment_filter,
					)

					await import_email(session, parsed, options, owner_id)
					stats["messages_imported"] += 1

					# Update last sync UID
					uid = await client.get_uid(msg_id)
					if uid:
						account.last_sync_uid = uid

				except Exception as e:
					stats["errors"].append(f"Failed to import message {msg_id}: {e}")

		# Update account sync time
		account.last_sync_at = datetime.utcnow()
		await session.commit()

	except Exception as e:
		stats["errors"].append(str(e))

	finally:
		await client.disconnect()

	return stats


async def test_graph_api_connection(account: EmailAccountModel) -> tuple[bool, str]:
	"""
	Test Microsoft Graph API connection for an email account.

	Uses OAuth2 credentials to verify access to the mailbox.
	"""
	import httpx
	from papermerge.core.security import decrypt_secret

	try:
		# Graph API requires OAuth2 tokens
		access_token = decrypt_secret(account.access_token_encrypted)
		if not access_token:
			return False, "No access token configured"

		async with httpx.AsyncClient() as client:
			# Test by fetching mailbox info
			response = await client.get(
				"https://graph.microsoft.com/v1.0/me/mailFolders/inbox",
				headers={
					"Authorization": f"Bearer {access_token}",
					"Content-Type": "application/json",
				},
				timeout=30.0,
			)

			if response.status_code == 200:
				data = response.json()
				total_items = data.get("totalItemCount", 0)
				unread_items = data.get("unreadItemCount", 0)
				return True, f"Connected to inbox. {total_items} total messages, {unread_items} unread."

			elif response.status_code == 401:
				return False, "Authentication failed. Token may be expired - please re-authorize."

			else:
				return False, f"API error: {response.status_code} - {response.text}"

	except httpx.TimeoutException:
		return False, "Connection timed out"

	except Exception as e:
		logger.error(f"Graph API connection test failed: {e}")
		return False, str(e)


async def test_gmail_api_connection(account: EmailAccountModel) -> tuple[bool, str]:
	"""
	Test Gmail API connection for an email account.

	Uses OAuth2 credentials to verify access to the mailbox.
	"""
	import httpx
	from papermerge.core.security import decrypt_secret

	try:
		access_token = decrypt_secret(account.access_token_encrypted)
		if not access_token:
			return False, "No access token configured"

		async with httpx.AsyncClient() as client:
			# Test by fetching mailbox profile
			response = await client.get(
				"https://gmail.googleapis.com/gmail/v1/users/me/profile",
				headers={
					"Authorization": f"Bearer {access_token}",
				},
				timeout=30.0,
			)

			if response.status_code == 200:
				data = response.json()
				email_address = data.get("emailAddress", "unknown")
				messages_total = data.get("messagesTotal", 0)
				return True, f"Connected to {email_address}. {messages_total} total messages."

			elif response.status_code == 401:
				return False, "Authentication failed. Token may be expired - please re-authorize."

			else:
				return False, f"API error: {response.status_code} - {response.text}"

	except httpx.TimeoutException:
		return False, "Connection timed out"

	except Exception as e:
		logger.error(f"Gmail API connection test failed: {e}")
		return False, str(e)
