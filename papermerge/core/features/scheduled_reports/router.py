# (c) Copyright Datacraft, 2026
"""REST endpoints for scheduled report management.

Auto-discovered by the router loader.

GET    /reports/scheduled          — list all scheduled reports for current tenant
POST   /reports/scheduled          — create a new scheduled report
PATCH  /reports/scheduled/{id}     — update an existing scheduled report
DELETE /reports/scheduled/{id}     — delete a scheduled report
POST   /reports/scheduled/{id}/send-now — trigger immediate delivery (test)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.users.schema import User

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ScheduledReportCreate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str = Field(..., min_length=1, max_length=200)
	report_type: str = Field(..., pattern="^(document_summary|ocr_quality|scanning_productivity|expiry_upcoming)$")
	schedule: str = Field(..., pattern="^(daily|weekly|monthly)$")
	delivery_hour: int = Field(8, ge=0, le=23)
	day_of_week: int | None = Field(None, ge=0, le=6)
	recipients: str = Field(..., min_length=1)
	format: str = Field("xlsx", pattern="^(csv|xlsx)$")
	filters: dict = Field(default_factory=dict)
	is_active: bool = True


class ScheduledReportUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str | None = Field(None, min_length=1, max_length=200)
	report_type: str | None = Field(None, pattern="^(document_summary|ocr_quality|scanning_productivity|expiry_upcoming)$")
	schedule: str | None = Field(None, pattern="^(daily|weekly|monthly)$")
	delivery_hour: int | None = Field(None, ge=0, le=23)
	day_of_week: int | None = None
	recipients: str | None = None
	format: str | None = Field(None, pattern="^(csv|xlsx)$")
	filters: dict | None = None
	is_active: bool | None = None


class ScheduledReportOut(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	name: str
	report_type: str
	schedule: str
	delivery_hour: int
	day_of_week: int | None
	recipients: str
	format: str
	filters: str
	is_active: bool
	last_sent_at: datetime | None
	send_count: int
	tenant_id: str
	created_by_id: str | None
	created_at: datetime

	@classmethod
	def from_orm_obj(cls, obj) -> "ScheduledReportOut":
		return cls(
			id=obj.id,
			name=obj.name,
			report_type=obj.report_type,
			schedule=obj.schedule,
			delivery_hour=obj.delivery_hour,
			day_of_week=obj.day_of_week,
			recipients=obj.recipients,
			format=obj.format,
			filters=obj.filters,
			is_active=obj.is_active,
			last_sent_at=obj.last_sent_at,
			send_count=obj.send_count,
			tenant_id=str(obj.tenant_id),
			created_by_id=str(obj.created_by_id) if obj.created_by_id else None,
			created_at=obj.created_at,
		)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_404(report_id: str, tenant_id: str, db: AsyncSession):
	from papermerge.core.features.scheduled_reports.db.orm import ScheduledReport
	import uuid

	result = await db.execute(
		select(ScheduledReport).where(
			ScheduledReport.id == report_id,
			ScheduledReport.tenant_id == uuid.UUID(tenant_id),
		)
	)
	obj = result.scalar_one_or_none()
	if obj is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled report not found")
	return obj


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
	"/scheduled",
	response_model=list[ScheduledReportOut],
	summary="List scheduled reports for the current tenant",
)
async def list_scheduled_reports(
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScheduledReportOut]:
	from papermerge.core.features.scheduled_reports.db.orm import ScheduledReport
	import uuid

	result = await db.execute(
		select(ScheduledReport)
		.where(ScheduledReport.tenant_id == uuid.UUID(str(user.tenant_id)))
		.order_by(ScheduledReport.created_at.desc())
	)
	return [ScheduledReportOut.from_orm_obj(r) for r in result.scalars().all()]


@router.post(
	"/scheduled",
	response_model=ScheduledReportOut,
	status_code=status.HTTP_201_CREATED,
	summary="Create a new scheduled report",
)
async def create_scheduled_report(
	body: ScheduledReportCreate,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduledReportOut:
	from papermerge.core.features.scheduled_reports.db.orm import ScheduledReport
	import uuid

	obj = ScheduledReport(
		name=body.name,
		report_type=body.report_type,
		schedule=body.schedule,
		delivery_hour=body.delivery_hour,
		day_of_week=body.day_of_week,
		recipients=body.recipients,
		format=body.format,
		filters=json.dumps(body.filters),
		is_active=body.is_active,
		tenant_id=uuid.UUID(str(user.tenant_id)),
		created_by_id=uuid.UUID(str(user.id)),
	)
	db.add(obj)
	await db.commit()
	await db.refresh(obj)
	_log.info("scheduled_reports: created '%s' (id=%s) for tenant=%s", obj.name, obj.id, user.tenant_id)
	return ScheduledReportOut.from_orm_obj(obj)


@router.patch(
	"/scheduled/{report_id}",
	response_model=ScheduledReportOut,
	summary="Update a scheduled report",
)
async def update_scheduled_report(
	report_id: str,
	body: ScheduledReportUpdate,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduledReportOut:
	obj = await _get_or_404(report_id, str(user.tenant_id), db)

	for field, value in body.model_dump(exclude_none=True).items():
		if field == "filters":
			setattr(obj, "filters", json.dumps(value))
		else:
			setattr(obj, field, value)

	await db.commit()
	await db.refresh(obj)
	return ScheduledReportOut.from_orm_obj(obj)


@router.delete(
	"/scheduled/{report_id}",
	status_code=status.HTTP_204_NO_CONTENT,
	summary="Delete a scheduled report",
)
async def delete_scheduled_report(
	report_id: str,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	obj = await _get_or_404(report_id, str(user.tenant_id), db)
	await db.delete(obj)
	await db.commit()
	_log.info("scheduled_reports: deleted report %s", report_id)


@router.post(
	"/scheduled/{report_id}/send-now",
	summary="Immediately send a scheduled report (test delivery)",
)
async def send_report_now(
	report_id: str,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
	"""
	Enqueue an immediate one-off delivery of the report without waiting for
	the scheduled hour.  Returns the Celery task id.
	"""
	# Verify the report exists and belongs to this tenant
	obj = await _get_or_404(report_id, str(user.tenant_id), db)

	from papermerge.core.features.scheduled_reports.tasks import run_scheduled_reports

	# We fire the general task; it will find this report due because we
	# temporarily patch nothing — instead we run a targeted async deliver.
	# For simplicity delegate to a lightweight inline approach:
	import asyncio
	import json as _json

	from papermerge.core.features.scheduled_reports.tasks import (
		_generate_report_bytes,
		_filename,
	)
	from papermerge.core.features.scheduled_reports.email_service import send_report_email

	try:
		filters = _json.loads(obj.filters or "{}")
		recipients = [r.strip() for r in obj.recipients.split(",") if r.strip()]
		if not recipients:
			raise HTTPException(status_code=400, detail="No recipients configured")

		file_bytes = await _generate_report_bytes(
			obj.report_type,
			obj.format,
			filters,
			str(obj.tenant_id),
			db,
		)
		fname = _filename(obj.name, obj.format)
		await send_report_email(
			recipients=recipients,
			report_name=obj.name,
			file_bytes=file_bytes,
			filename=fname,
			report_type=obj.report_type,
		)

		# Update send metadata
		obj.last_sent_at = datetime.now(tz=timezone.utc)
		obj.send_count = (obj.send_count or 0) + 1
		await db.commit()

		_log.info("scheduled_reports: manual send-now for report %s to %s", report_id, recipients)
		return {"sent": True, "recipients": recipients, "filename": fname}

	except HTTPException:
		raise
	except Exception as exc:
		_log.error("scheduled_reports: send-now failed for %s: %s", report_id, exc, exc_info=True)
		raise HTTPException(status_code=500, detail=f"Delivery failed: {exc}") from exc
