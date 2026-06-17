# (c) Copyright Datacraft, 2026
"""Email ingestion (IMAP) API endpoints.

Auto-discovered by the router registry — no manual wiring needed in app.py.
"""
import imaplib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from .db.orm import EmailIngestConfig
from .service import _decrypt_password, _encrypt_password

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/email-ingest",
	tags=["email-ingest"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class EmailIngestConfigCreate(BaseModel):
	name: str
	host: str
	port: int = 993
	username: str
	password: str
	use_ssl: bool = True
	mailbox_folder: str = "INBOX"
	check_interval_minutes: int = 15
	destination_folder_id: str | None = None
	project_id: str | None = None
	is_active: bool = True
	allowed_senders: str = ""


class EmailIngestConfigUpdate(BaseModel):
	name: str | None = None
	host: str | None = None
	port: int | None = None
	username: str | None = None
	password: str | None = None
	use_ssl: bool | None = None
	mailbox_folder: str | None = None
	check_interval_minutes: int | None = None
	destination_folder_id: str | None = None
	project_id: str | None = None
	is_active: bool | None = None
	allowed_senders: str | None = None


class EmailIngestConfigOut(BaseModel):
	id: str
	name: str
	host: str
	port: int
	username: str
	use_ssl: bool
	mailbox_folder: str
	check_interval_minutes: int
	destination_folder_id: str | None
	project_id: str | None
	is_active: bool
	allowed_senders: str
	last_processed_uid: int
	last_checked_at: datetime | None
	documents_ingested: int
	tenant_id: str
	created_by_id: str
	created_at: datetime

	model_config = {"from_attributes": True}


class EmailTestResult(BaseModel):
	success: bool
	error: str | None = None
	folders: list[str] | None = None
	unseen_count: int | None = None


class TriggerResult(BaseModel):
	queued: int
	error: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/configs", response_model=list[EmailIngestConfigOut])
async def list_configs(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> list[EmailIngestConfigOut]:
	"""List all IMAP email ingest configs for the current tenant."""
	stmt = (
		select(EmailIngestConfig)
		.where(EmailIngestConfig.tenant_id == str(user.tenant_id))
		.order_by(EmailIngestConfig.created_at.desc())
	)
	result = await db_session.execute(stmt)
	configs = result.scalars().all()
	return [EmailIngestConfigOut.model_validate(c) for c in configs]


@router.post("/configs", response_model=EmailIngestConfigOut, status_code=201)
async def create_config(
	payload: EmailIngestConfigCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> EmailIngestConfigOut:
	"""Create a new IMAP email ingest config."""
	config = EmailIngestConfig(
		name=payload.name,
		host=payload.host,
		port=payload.port,
		username=payload.username,
		encrypted_password=_encrypt_password(payload.password),
		use_ssl=payload.use_ssl,
		mailbox_folder=payload.mailbox_folder,
		check_interval_minutes=payload.check_interval_minutes,
		destination_folder_id=payload.destination_folder_id,
		project_id=payload.project_id,
		is_active=payload.is_active,
		allowed_senders=payload.allowed_senders,
		tenant_id=str(user.tenant_id),
		created_by_id=str(user.id),
	)
	db_session.add(config)
	await db_session.commit()
	await db_session.refresh(config)
	return EmailIngestConfigOut.model_validate(config)


@router.patch("/configs/{config_id}", response_model=EmailIngestConfigOut)
async def update_config(
	config_id: str,
	payload: EmailIngestConfigUpdate,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> EmailIngestConfigOut:
	"""Update an existing IMAP email ingest config."""
	config = await db_session.get(EmailIngestConfig, config_id)
	if not config or config.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=404, detail="Email ingest config not found")

	update_data = payload.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		if field == "password":
			config.encrypted_password = _encrypt_password(value)
		else:
			setattr(config, field, value)

	await db_session.commit()
	await db_session.refresh(config)
	return EmailIngestConfigOut.model_validate(config)


@router.delete("/configs/{config_id}", status_code=204)
async def delete_config(
	config_id: str,
	user: require_scopes(scopes.NODE_DELETE),
	db_session: AsyncSession = Depends(get_db),
) -> None:
	"""Delete an IMAP email ingest config."""
	config = await db_session.get(EmailIngestConfig, config_id)
	if not config or config.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=404, detail="Email ingest config not found")
	await db_session.delete(config)
	await db_session.commit()


@router.post("/configs/{config_id}/test", response_model=EmailTestResult)
async def test_config(
	config_id: str,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> EmailTestResult:
	"""Test connectivity to an IMAP server.

	Returns success flag, folder list, and unseen message count.
	"""
	config = await db_session.get(EmailIngestConfig, config_id)
	if not config or config.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=404, detail="Email ingest config not found")

	password = _decrypt_password(config.encrypted_password)

	try:
		if config.use_ssl:
			imap = imaplib.IMAP4_SSL(config.host, config.port)
		else:
			imap = imaplib.IMAP4(config.host, config.port)

		imap.login(config.username, password)

		# List available folders
		typ, folder_data = imap.list()
		folders: list[str] = []
		if typ == "OK":
			for item in folder_data or []:
				if isinstance(item, bytes):
					# parse the last quoted/unquoted token as folder name
					parts = item.decode().split('"')
					name = parts[-1].strip().strip('"') if len(parts) > 1 else item.decode().split()[-1]
					folders.append(name)

		# Count unseen in configured mailbox
		imap.select(config.mailbox_folder, readonly=True)
		typ2, data2 = imap.search(None, "UNSEEN")
		unseen_count = 0
		if typ2 == "OK" and data2 and data2[0]:
			unseen_count = len(data2[0].split())

		imap.logout()
		return EmailTestResult(success=True, folders=folders, unseen_count=unseen_count)

	except imaplib.IMAP4.error as exc:
		logger.warning("email_ingest test failed for config %s: %s", config_id[:8], exc)
		return EmailTestResult(success=False, error=str(exc))
	except Exception as exc:
		logger.warning("email_ingest test unexpected error config %s: %s", config_id[:8], exc)
		return EmailTestResult(success=False, error=str(exc))


@router.post("/configs/{config_id}/trigger", response_model=TriggerResult)
async def trigger_config(
	config_id: str,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> TriggerResult:
	"""Manually trigger an immediate mailbox check for one config."""
	config = await db_session.get(EmailIngestConfig, config_id)
	if not config or config.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=404, detail="Email ingest config not found")

	try:
		from papermerge.core.features.email_ingest.tasks import check_mailbox_task
		check_mailbox_task.delay(config_id)
		return TriggerResult(queued=1)
	except Exception as exc:
		logger.warning("email_ingest trigger failed for config %s: %s", config_id[:8], exc)
		return TriggerResult(queued=0, error=str(exc))
