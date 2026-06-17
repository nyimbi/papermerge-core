# (c) Copyright Datacraft, 2026
"""SFTP/FTP ingestion connector API endpoints.

Auto-discovered by the router registry — no manual wiring needed in app.py.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from .db.orm import SftpConnection, SftpDownloadedFile

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/ingestion",
	tags=["ingestion", "sftp"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas (kept local — simple enough not to warrant a schema.py)
# ---------------------------------------------------------------------------

class SftpConnectionCreate(BaseModel):
	name: str
	host: str
	port: int = 22
	username: str
	password: str | None = None        # plaintext — encrypted before storage
	ssh_key: str | None = None         # plaintext private key — encrypted before storage
	remote_path: str = "/"
	file_pattern: str = "*.pdf,*.tiff,*.jpg"
	poll_interval_minutes: int = 5
	destination_folder_id: str | None = None
	is_active: bool = True


class SftpConnectionUpdate(BaseModel):
	name: str | None = None
	host: str | None = None
	port: int | None = None
	username: str | None = None
	password: str | None = None
	ssh_key: str | None = None
	remote_path: str | None = None
	file_pattern: str | None = None
	poll_interval_minutes: int | None = None
	destination_folder_id: str | None = None
	is_active: bool | None = None


class SftpConnectionOut(BaseModel):
	id: str
	name: str
	host: str
	port: int
	username: str
	remote_path: str
	file_pattern: str
	poll_interval_minutes: int
	destination_folder_id: str | None
	is_active: bool
	last_polled_at: datetime | None
	last_error: str | None
	docs_ingested_total: int
	tenant_id: str
	created_at: datetime

	model_config = {"from_attributes": True}


class SftpTestResult(BaseModel):
	success: bool
	error: str | None = None
	file_count: int | None = None


class SftpActivityItem(BaseModel):
	id: str
	remote_path: str
	file_size: int
	downloaded_at: datetime

	model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def _encrypt(plaintext: str) -> str:
	"""Encrypt a secret string.

	Uses Fernet symmetric encryption when the `cryptography` package is
	available and SFTP_ENCRYPTION_KEY is set in the environment.
	Falls back to base64 (obfuscation only) so the app never hard-crashes
	on environments without the package.
	"""
	import os, base64
	key_b64 = os.environ.get("SFTP_ENCRYPTION_KEY")
	if key_b64:
		try:
			from cryptography.fernet import Fernet
			f = Fernet(key_b64.encode())
			return f.encrypt(plaintext.encode()).decode()
		except Exception as exc:
			logger.warning("Fernet encryption failed, falling back to base64: %s", exc)
	return base64.b64encode(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
	"""Decrypt a secret stored by _encrypt()."""
	import os, base64
	key_b64 = os.environ.get("SFTP_ENCRYPTION_KEY")
	if key_b64:
		try:
			from cryptography.fernet import Fernet
			f = Fernet(key_b64.encode())
			return f.decrypt(ciphertext.encode()).decode()
		except Exception:
			pass
	try:
		return base64.b64decode(ciphertext.encode()).decode()
	except Exception:
		return ciphertext


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/sftp-connections", response_model=list[SftpConnectionOut])
async def list_sftp_connections(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> list[SftpConnectionOut]:
	"""List all SFTP/FTP connections for the current tenant."""
	stmt = select(SftpConnection).where(
		SftpConnection.tenant_id == str(user.tenant_id)
	).order_by(SftpConnection.created_at.desc())
	result = await db_session.execute(stmt)
	connections = result.scalars().all()
	return [SftpConnectionOut.model_validate(c) for c in connections]


@router.post("/sftp-connections", response_model=SftpConnectionOut, status_code=201)
async def create_sftp_connection(
	payload: SftpConnectionCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> SftpConnectionOut:
	"""Create a new SFTP/FTP connection."""
	conn = SftpConnection(
		name=payload.name,
		host=payload.host,
		port=payload.port,
		username=payload.username,
		password_encrypted=_encrypt(payload.password) if payload.password else None,
		ssh_key_encrypted=_encrypt(payload.ssh_key) if payload.ssh_key else None,
		remote_path=payload.remote_path,
		file_pattern=payload.file_pattern,
		poll_interval_minutes=payload.poll_interval_minutes,
		destination_folder_id=payload.destination_folder_id,
		is_active=payload.is_active,
		tenant_id=str(user.tenant_id),
	)
	db_session.add(conn)
	await db_session.commit()
	await db_session.refresh(conn)
	return SftpConnectionOut.model_validate(conn)


@router.patch("/sftp-connections/{connection_id}", response_model=SftpConnectionOut)
async def update_sftp_connection(
	connection_id: str,
	payload: SftpConnectionUpdate,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> SftpConnectionOut:
	"""Update an existing SFTP/FTP connection."""
	conn = await db_session.get(SftpConnection, connection_id)
	if not conn or conn.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=404, detail="SFTP connection not found")

	update_data = payload.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		if field == "password":
			conn.password_encrypted = _encrypt(value) if value else None
		elif field == "ssh_key":
			conn.ssh_key_encrypted = _encrypt(value) if value else None
		else:
			setattr(conn, field, value)

	await db_session.commit()
	await db_session.refresh(conn)
	return SftpConnectionOut.model_validate(conn)


@router.delete("/sftp-connections/{connection_id}", status_code=204)
async def delete_sftp_connection(
	connection_id: str,
	user: require_scopes(scopes.NODE_DELETE),
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Delete an SFTP/FTP connection and all associated download history."""
	conn = await db_session.get(SftpConnection, connection_id)
	if not conn or conn.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=404, detail="SFTP connection not found")

	await db_session.delete(conn)
	await db_session.commit()


@router.post("/sftp-connections/{connection_id}/test", response_model=SftpTestResult)
async def test_sftp_connection(
	connection_id: str,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> SftpTestResult:
	"""Test connectivity to an SFTP/FTP server.

	Returns {success, error?, file_count?}.
	"""
	conn = await db_session.get(SftpConnection, connection_id)
	if not conn or conn.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=404, detail="SFTP connection not found")

	password = _decrypt(conn.password_encrypted) if conn.password_encrypted else None
	ssh_key = _decrypt(conn.ssh_key_encrypted) if conn.ssh_key_encrypted else None

	try:
		import paramiko  # type: ignore[import]

		client = paramiko.SSHClient()
		client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

		connect_kwargs: dict[str, Any] = {
			"hostname": conn.host,
			"port": conn.port,
			"username": conn.username,
			"timeout": 10,
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

		# Count files matching each pattern
		patterns = [p.strip() for p in conn.file_pattern.split(",") if p.strip()]
		import fnmatch
		all_entries = sftp.listdir()
		matching = [
			f for f in all_entries
			if any(fnmatch.fnmatch(f, pat) for pat in patterns)
		]
		file_count = len(matching)

		sftp.close()
		client.close()
		return SftpTestResult(success=True, file_count=file_count)

	except ImportError:
		# paramiko not installed — try ftplib as FTP fallback
		import ftplib
		try:
			ftp = ftplib.FTP()
			ftp.connect(conn.host, conn.port if conn.port != 22 else 21, timeout=10)
			ftp.login(conn.username, password or "")
			ftp.cwd(conn.remote_path)
			entries = ftp.nlst()
			import fnmatch
			patterns = [p.strip() for p in conn.file_pattern.split(",") if p.strip()]
			matching = [
				f for f in entries
				if any(fnmatch.fnmatch(f, pat) for pat in patterns)
			]
			ftp.quit()
			return SftpTestResult(success=True, file_count=len(matching))
		except Exception as ftp_exc:
			return SftpTestResult(success=False, error=f"FTP error: {ftp_exc}")

	except Exception as exc:
		logger.warning("SFTP test failed for connection %s: %s", connection_id, exc)
		return SftpTestResult(success=False, error=str(exc))


@router.get(
	"/sftp-connections/{connection_id}/activity",
	response_model=list[SftpActivityItem],
)
async def get_sftp_activity(
	connection_id: str,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> list[SftpActivityItem]:
	"""Return the 20 most recently downloaded files for a connection."""
	conn = await db_session.get(SftpConnection, connection_id)
	if not conn or conn.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=404, detail="SFTP connection not found")

	stmt = (
		select(SftpDownloadedFile)
		.where(SftpDownloadedFile.connection_id == connection_id)
		.order_by(SftpDownloadedFile.downloaded_at.desc())
		.limit(20)
	)
	result = await db_session.execute(stmt)
	items = result.scalars().all()
	return [SftpActivityItem.model_validate(i) for i in items]
