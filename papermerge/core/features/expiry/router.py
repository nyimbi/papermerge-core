# (c) Copyright Datacraft, 2026
"""FastAPI router for document expiry reminders."""
import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.users.schema import User
from papermerge.core.features.expiry.db.orm import DocumentExpiry
from papermerge.core.utils.uuid_compat import uuid7str

logger = logging.getLogger(__name__)

router = APIRouter(tags=["expiry"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ExpiryResponse(BaseModel):
	document_id: str
	expires_at: datetime
	reminder_days: list[int]
	notified_milestones: list[int]
	created_by_id: str | None
	tenant_id: str
	created_at: datetime
	updated_at: datetime

	model_config = {"from_attributes": True}


class ExpiryUpsert(BaseModel):
	expires_at: datetime
	reminder_days: list[int] = [30, 7, 1]


class UpcomingExpiryItem(BaseModel):
	document_id: str
	expires_at: datetime
	days_until_expiry: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _expiry_or_404(record: DocumentExpiry | None, document_id: str) -> DocumentExpiry:
	if record is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail=f"No expiry record for document {document_id!r}",
		)
	return record


def _to_response(record: DocumentExpiry) -> ExpiryResponse:
	return ExpiryResponse(
		document_id=record.document_id,
		expires_at=record.expires_at,
		reminder_days=json.loads(record.reminder_days),
		notified_milestones=json.loads(record.notified_milestones),
		created_by_id=record.created_by_id,
		tenant_id=record.tenant_id,
		created_at=record.created_at,
		updated_at=record.updated_at,
	)


# ---------------------------------------------------------------------------
# Per-document routes
# ---------------------------------------------------------------------------


@router.get("/documents/{document_id}/expiry", response_model=ExpiryResponse)
async def get_document_expiry(
	document_id: str,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> ExpiryResponse:
	"""Return the expiry settings for a document."""
	stmt = select(DocumentExpiry).where(DocumentExpiry.document_id == document_id)
	result = await db.execute(stmt)
	record = result.scalar_one_or_none()
	_expiry_or_404(record, document_id)
	assert record is not None
	if record.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
	return _to_response(record)


@router.put(
	"/documents/{document_id}/expiry",
	response_model=ExpiryResponse,
	status_code=status.HTTP_200_OK,
)
async def upsert_document_expiry(
	document_id: str,
	body: ExpiryUpsert,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> ExpiryResponse:
	"""Create or update expiry settings for a document."""
	stmt = select(DocumentExpiry).where(DocumentExpiry.document_id == document_id)
	result = await db.execute(stmt)
	record = result.scalar_one_or_none()

	now = _now_utc()
	if record is None:
		record = DocumentExpiry(
			id=uuid7str(),
			document_id=document_id,
			expires_at=body.expires_at,
			reminder_days=json.dumps(body.reminder_days),
			notified_milestones="[]",
			created_by_id=str(user.id),
			tenant_id=str(user.tenant_id),
			created_at=now,
			updated_at=now,
		)
		db.add(record)
		logger.info("Document expiry created: doc=%s user=%s", document_id, user.id)
	else:
		if record.tenant_id != str(user.tenant_id):
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
		record.expires_at = body.expires_at
		record.reminder_days = json.dumps(body.reminder_days)
		# Reset notified milestones when expiry date changes so reminders re-fire
		record.notified_milestones = "[]"
		record.updated_at = now
		logger.info("Document expiry updated: doc=%s user=%s", document_id, user.id)

	await db.commit()
	await db.refresh(record)
	return _to_response(record)


@router.delete("/documents/{document_id}/expiry", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_expiry(
	document_id: str,
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> None:
	"""Remove expiry settings for a document."""
	stmt = select(DocumentExpiry).where(DocumentExpiry.document_id == document_id)
	result = await db.execute(stmt)
	record = result.scalar_one_or_none()
	_expiry_or_404(record, document_id)
	assert record is not None
	if record.tenant_id != str(user.tenant_id):
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
	await db.delete(record)
	await db.commit()
	logger.info("Document expiry deleted: doc=%s user=%s", document_id, user.id)


# ---------------------------------------------------------------------------
# Tenant-wide upcoming expiries
# ---------------------------------------------------------------------------


@router.get("/expiry/upcoming", response_model=list[UpcomingExpiryItem])
async def list_upcoming_expiries(
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
	days: int = Query(default=30, ge=1, le=365),
) -> list[UpcomingExpiryItem]:
	"""List all documents expiring within the next N days for the current tenant."""
	from datetime import timedelta

	now = _now_utc()
	cutoff = now + timedelta(days=days)

	stmt = (
		select(DocumentExpiry)
		.where(
			DocumentExpiry.tenant_id == str(user.tenant_id),
			DocumentExpiry.expires_at >= now,
			DocumentExpiry.expires_at <= cutoff,
		)
		.order_by(DocumentExpiry.expires_at.asc())
	)
	result = await db.execute(stmt)
	records = result.scalars().all()

	items: list[UpcomingExpiryItem] = []
	for r in records:
		delta = r.expires_at - now
		days_until = max(0, delta.days)
		items.append(
			UpcomingExpiryItem(
				document_id=r.document_id,
				expires_at=r.expires_at,
				days_until_expiry=days_until,
			)
		)
	return items
