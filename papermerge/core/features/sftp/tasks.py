# (c) Copyright Datacraft, 2026
"""Celery tasks for SFTP/FTP ingestion polling.

# WIRING NEEDED: Add to celery_app.py:
# task_routes = {
#     ...
#     "darchiva.ingestion.poll_sftp_connection": {"queue": prefixed("core")},
#     "darchiva.ingestion.poll_all_sftp": {"queue": prefixed("core")},
# }
# beat_schedule = {
#     ...
#     "poll-all-sftp": {
#         "task": "darchiva.ingestion.poll_all_sftp",
#         "schedule": 300.0,  # every 5 minutes
#     },
# }
"""
import asyncio
import fnmatch
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Encryption helpers (mirrored from router.py to avoid circular import)
# ---------------------------------------------------------------------------

def _decrypt(ciphertext: str) -> str:
	key_b64 = os.environ.get("SFTP_ENCRYPTION_KEY")
	if key_b64:
		try:
			from cryptography.fernet import Fernet
			return Fernet(key_b64.encode()).decrypt(ciphertext.encode()).decode()
		except Exception:
			pass
	import base64
	try:
		return base64.b64decode(ciphertext.encode()).decode()
	except Exception:
		return ciphertext


# ---------------------------------------------------------------------------
# Core polling logic (async so it can use the async DB session)
# ---------------------------------------------------------------------------

async def _poll_connection(connection_id: str) -> dict:
	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.features.sftp.db.orm import SftpConnection, SftpDownloadedFile
	from sqlalchemy import select

	async_session = get_async_session_maker()

	async with async_session() as session:
		conn = await session.get(SftpConnection, connection_id)
		if not conn:
			logger.error("SftpConnection not found: %s", connection_id)
			return {"downloaded": 0, "skipped": 0, "errors": 1}

		if not conn.is_active:
			logger.info("SftpConnection inactive, skipping: %s", connection_id[:8])
			return {"downloaded": 0, "skipped": 0, "errors": 0}

		password = _decrypt(conn.password_encrypted) if conn.password_encrypted else None
		ssh_key = _decrypt(conn.ssh_key_encrypted) if conn.ssh_key_encrypted else None
		patterns = [p.strip() for p in conn.file_pattern.split(",") if p.strip()]

		# Build list of already-downloaded remote paths for this connection
		already_stmt = select(SftpDownloadedFile.remote_path).where(
			SftpDownloadedFile.connection_id == connection_id
		)
		already_result = await session.execute(already_stmt)
		already_downloaded: set[str] = {row[0] for row in already_result.all()}

		tmp_dir = Path(tempfile.gettempdir()) / f"sftp_{connection_id}"
		tmp_dir.mkdir(parents=True, exist_ok=True)

		downloaded = 0
		skipped = 0
		last_error: str | None = None

		try:
			remote_files = await asyncio.to_thread(
				_list_remote_files, conn, password, ssh_key, patterns
			)
		except Exception as exc:
			last_error = str(exc)
			logger.error("Failed to list remote files for %s: %s", connection_id[:8], exc)
			conn.last_error = last_error
			conn.last_polled_at = datetime.utcnow()
			await session.commit()
			return {"downloaded": 0, "skipped": 0, "errors": 1}

		for remote_file_path, file_size in remote_files:
			if remote_file_path in already_downloaded:
				skipped += 1
				continue

			local_path = tmp_dir / Path(remote_file_path).name
			try:
				await asyncio.to_thread(
					_download_file, conn, password, ssh_key, remote_file_path, str(local_path)
				)
			except Exception as exc:
				last_error = str(exc)
				logger.warning(
					"Failed to download %s from %s: %s",
					remote_file_path, connection_id[:8], exc
				)
				continue

			# Fan out to process_upload task
			try:
				from papermerge.core.tasks import send_task
				send_task(
					"darchiva.ingestion.process_upload",
					kwargs={
						"file_path": str(local_path),
						"tenant_id": conn.tenant_id,
						"destination_folder_id": conn.destination_folder_id,
						"source": f"sftp:{connection_id}:{remote_file_path}",
					},
				)
			except Exception as exc:
				logger.warning("Failed to queue process_upload for %s: %s", remote_file_path, exc)

			# Record the downloaded file
			record = SftpDownloadedFile(
				connection_id=connection_id,
				remote_path=remote_file_path,
				file_size=file_size,
			)
			session.add(record)
			downloaded += 1

		# Update connection state
		conn.last_polled_at = datetime.utcnow()
		conn.last_error = last_error
		if downloaded:
			conn.docs_ingested_total = (conn.docs_ingested_total or 0) + downloaded

		await session.commit()

	logger.info(
		"poll_sftp_connection %s: downloaded=%d skipped=%d",
		connection_id[:8], downloaded, skipped,
	)
	return {"downloaded": downloaded, "skipped": skipped, "errors": 0 if not last_error else 1}


def _list_remote_files(
	conn: Any, password: str | None, ssh_key: str | None, patterns: list[str]
) -> list[tuple[str, int]]:
	"""Return list of (remote_path, file_size) matching patterns.

	Tries paramiko (SFTP) first, falls back to ftplib (FTP).
	"""
	try:
		import paramiko  # type: ignore[import]

		client = paramiko.SSHClient()
		client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

		connect_kwargs: dict[str, Any] = {
			"hostname": conn.host,
			"port": conn.port,
			"username": conn.username,
			"timeout": 30,
		}
		if ssh_key:
			import io
			pkey = paramiko.RSAKey.from_private_key(io.StringIO(ssh_key))
			connect_kwargs["pkey"] = pkey
		elif password:
			connect_kwargs["password"] = password

		client.connect(**connect_kwargs)
		sftp = client.open_sftp()
		sftp.chdir(conn.remote_path)

		results: list[tuple[str, int]] = []
		for entry in sftp.listdir_attr():
			if entry.filename and any(fnmatch.fnmatch(entry.filename, p) for p in patterns):
				remote_path = f"{conn.remote_path.rstrip('/')}/{entry.filename}"
				results.append((remote_path, entry.st_size or 0))

		sftp.close()
		client.close()
		return results

	except ImportError:
		# ftplib fallback
		import ftplib

		ftp = ftplib.FTP()
		ftp.connect(conn.host, conn.port if conn.port != 22 else 21, timeout=30)
		ftp.login(conn.username, password or "")
		ftp.cwd(conn.remote_path)

		results = []
		entries = ftp.nlst()
		for filename in entries:
			if any(fnmatch.fnmatch(filename, p) for p in patterns):
				try:
					size = ftp.size(filename) or 0
				except Exception:
					size = 0
				remote_path = f"{conn.remote_path.rstrip('/')}/{filename}"
				results.append((remote_path, size))

		ftp.quit()
		return results


def _download_file(
	conn: Any,
	password: str | None,
	ssh_key: str | None,
	remote_path: str,
	local_path: str,
) -> None:
	"""Download a single file via SFTP (paramiko) or FTP (ftplib)."""
	try:
		import paramiko  # type: ignore[import]

		client = paramiko.SSHClient()
		client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

		connect_kwargs: dict[str, Any] = {
			"hostname": conn.host,
			"port": conn.port,
			"username": conn.username,
			"timeout": 60,
		}
		if ssh_key:
			import io
			pkey = paramiko.RSAKey.from_private_key(io.StringIO(ssh_key))
			connect_kwargs["pkey"] = pkey
		elif password:
			connect_kwargs["password"] = password

		client.connect(**connect_kwargs)
		sftp = client.open_sftp()
		sftp.get(remote_path, local_path)
		sftp.close()
		client.close()

	except ImportError:
		import ftplib

		ftp = ftplib.FTP()
		ftp.connect(conn.host, conn.port if conn.port != 22 else 21, timeout=60)
		ftp.login(conn.username, password or "")
		with open(local_path, "wb") as f:
			ftp.retrbinary(f"RETR {remote_path}", f.write)
		ftp.quit()


# ---------------------------------------------------------------------------
# Celery shared tasks
# ---------------------------------------------------------------------------

@shared_task(
	bind=True,
	max_retries=3,
	default_retry_delay=60,
	name="darchiva.ingestion.poll_sftp_connection",
)
def poll_sftp_connection(self, connection_id: str) -> dict:
	"""Poll one SFTP/FTP connection for new files and fan out process_upload tasks.

	Retries up to 3 times on unexpected failure with 60s delay.
	Returns {downloaded, skipped, errors}.
	"""
	logger.info("poll_sftp_connection: %s", connection_id[:8])
	try:
		return asyncio.run(_poll_connection(connection_id))
	except Exception as exc:
		logger.warning(
			"poll_sftp_connection failed for %s, retry %d/%d: %s",
			connection_id[:8], self.request.retries, self.max_retries, exc,
		)
		raise self.retry(exc=exc)


@shared_task(name="darchiva.ingestion.poll_all_sftp")
def poll_all_sftp_connections() -> dict:
	"""Poll all active SFTP/FTP connections that are due for sync.

	Called by Celery beat every 5 minutes (configured in celery_app.py).
	Fans out poll_sftp_connection.delay(id) for each active connection
	whose poll interval has elapsed since last_polled_at.

	Returns {queued, skipped}.
	"""
	logger.info("poll_all_sftp_connections: scanning active connections")

	async def _find_due() -> list[str]:
		from papermerge.core.db.engine import get_async_session_maker
		from papermerge.core.features.sftp.db.orm import SftpConnection
		from sqlalchemy import select

		async_session = get_async_session_maker()
		now = datetime.utcnow()

		async with async_session() as session:
			stmt = select(SftpConnection).where(SftpConnection.is_active == True)
			result = await session.execute(stmt)
			connections = result.scalars().all()

			due = []
			for c in connections:
				if c.last_polled_at is None:
					due.append(c.id)
					continue
				elapsed_minutes = (now - c.last_polled_at).total_seconds() / 60
				if elapsed_minutes >= c.poll_interval_minutes:
					due.append(c.id)

			return due

	due_ids = asyncio.run(_find_due())

	queued = 0
	for cid in due_ids:
		poll_sftp_connection.delay(cid)
		queued += 1

	logger.info("poll_all_sftp_connections: queued=%d", queued)
	return {"queued": queued, "skipped": 0}
