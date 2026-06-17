# (c) Copyright Datacraft, 2026
"""IMAP mailbox polling logic for email ingestion.

Uses stdlib imaplib + email — no third-party mail library required.
"""
import base64
import email
import imaplib
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from .db.orm import EmailIngestConfig

logger = logging.getLogger(__name__)

# Attachment MIME types we are willing to ingest
_INGEST_MIME_TYPES = {
	"application/pdf",
	"image/tiff",
	"image/tif",
	"image/jpeg",
	"image/jpg",
	"image/png",
}
_INGEST_EXTENSIONS = {".pdf", ".tiff", ".tif", ".jpg", ".jpeg", ".png"}


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def _encrypt_password(plaintext: str) -> str:
	"""Encrypt with Fernet when IMAP_ENCRYPTION_KEY is set, else base64."""
	key_b64 = os.environ.get("IMAP_ENCRYPTION_KEY")
	if key_b64:
		try:
			from cryptography.fernet import Fernet
			return Fernet(key_b64.encode()).encrypt(plaintext.encode()).decode()
		except Exception as exc:
			logger.warning("Fernet encryption failed, falling back to base64: %s", exc)
	return base64.b64encode(plaintext.encode()).decode()


def _decrypt_password(ciphertext: str) -> str:
	"""Decrypt a password stored by _encrypt_password()."""
	key_b64 = os.environ.get("IMAP_ENCRYPTION_KEY")
	if key_b64:
		try:
			from cryptography.fernet import Fernet
			return Fernet(key_b64.encode()).decrypt(ciphertext.encode()).decode()
		except Exception:
			pass
	try:
		return base64.b64decode(ciphertext.encode()).decode()
	except Exception:
		return ciphertext


# ---------------------------------------------------------------------------
# Core mailbox check
# ---------------------------------------------------------------------------

async def check_mailbox(config: EmailIngestConfig, session: AsyncSession) -> int:
	"""Connect to the IMAP server and ingest new attachment-bearing messages.

	Returns the count of new documents queued for processing.
	"""
	password = _decrypt_password(config.encrypted_password)

	# Determine which senders are allowed (empty = all)
	allowed: set[str] = set()
	if config.allowed_senders.strip():
		allowed = {s.strip().lower() for s in config.allowed_senders.split(",") if s.strip()}

	new_docs = 0
	max_uid = config.last_processed_uid

	tmp_dir = Path(tempfile.gettempdir()) / f"email_ingest_{config.id}"
	tmp_dir.mkdir(parents=True, exist_ok=True)

	try:
		if config.use_ssl:
			imap = imaplib.IMAP4_SSL(config.host, config.port)
		else:
			imap = imaplib.IMAP4(config.host, config.port)

		imap.login(config.username, password)
		imap.select(config.mailbox_folder, readonly=False)

		# Search for messages with UID > last_processed_uid
		# imaplib UID SEARCH returns UIDs as bytes
		search_criteria = f"UID {config.last_processed_uid + 1}:*"
		typ, data = imap.uid("SEARCH", None, search_criteria)
		if typ != "OK" or not data or not data[0]:
			imap.logout()
			_update_stats(config, max_uid, new_docs)
			await session.commit()
			return 0

		uid_list = data[0].split()
		if not uid_list:
			imap.logout()
			_update_stats(config, max_uid, new_docs)
			await session.commit()
			return 0

		for uid_bytes in uid_list:
			uid = int(uid_bytes)
			if uid <= config.last_processed_uid:
				continue

			# Fetch the full RFC822 message
			typ, msg_data = imap.uid("FETCH", uid_bytes, "(RFC822)")
			if typ != "OK" or not msg_data or not msg_data[0]:
				continue

			raw = msg_data[0][1]  # type: ignore[index]
			msg = email.message_from_bytes(raw)

			# Sender filter
			from_hdr = msg.get("From", "")
			sender_addr = email.utils.parseaddr(from_hdr)[1].lower()
			if allowed and sender_addr not in allowed:
				logger.debug("email_ingest: skipping UID %d from %s (not in allowed_senders)", uid, sender_addr)
				max_uid = max(max_uid, uid)
				continue

			# Extract PDF/image attachments
			attachments = _extract_attachments(msg)
			if not attachments:
				max_uid = max(max_uid, uid)
				continue

			for filename, payload in attachments:
				local_path = tmp_dir / filename
				local_path.write_bytes(payload)

				try:
					from papermerge.core.tasks import send_task
					send_task(
						"darchiva.ingestion.process_upload",
						kwargs={
							"file_path": str(local_path),
							"tenant_id": config.tenant_id,
							"destination_folder_id": config.destination_folder_id,
							"project_id": config.project_id,
							"source": f"email_ingest:{config.id}:uid={uid}:{filename}",
						},
					)
					new_docs += 1
				except Exception as exc:
					logger.warning(
						"email_ingest: failed to queue %s from UID %d: %s",
						filename, uid, exc,
					)

			max_uid = max(max_uid, uid)

		imap.logout()

	except Exception as exc:
		logger.error("email_ingest check_mailbox failed for config %s: %s", config.id[:8], exc)
		config.last_checked_at = datetime.now(tz=timezone.utc)
		await session.commit()
		raise

	_update_stats(config, max_uid, new_docs)
	await session.commit()
	logger.info(
		"email_ingest config=%s: %d new documents queued, last_uid=%d",
		config.id[:8], new_docs, max_uid,
	)
	return new_docs


def _update_stats(config: EmailIngestConfig, max_uid: int, new_docs: int) -> None:
	config.last_processed_uid = max_uid
	config.last_checked_at = datetime.now(tz=timezone.utc)
	if new_docs:
		config.documents_ingested = (config.documents_ingested or 0) + new_docs


def _extract_attachments(msg: email.message.Message) -> list[tuple[str, bytes]]:
	"""Return list of (filename, bytes) for PDF/image attachments in the message."""
	results: list[tuple[str, bytes]] = []
	for part in msg.walk():
		content_disp = part.get_content_disposition() or ""
		content_type = part.get_content_type().lower()

		is_attachment = "attachment" in content_disp
		is_ingest_mime = content_type in _INGEST_MIME_TYPES

		filename = part.get_filename()
		if filename:
			ext = Path(filename).suffix.lower()
			is_ingest_ext = ext in _INGEST_EXTENSIONS
		else:
			is_ingest_ext = False

		if not (is_attachment or is_ingest_mime or is_ingest_ext):
			continue
		if not filename:
			continue

		payload = part.get_payload(decode=True)
		if not payload:
			continue

		# Sanitise filename
		safe_name = Path(filename).name
		results.append((safe_name, payload))  # type: ignore[arg-type]

	return results
