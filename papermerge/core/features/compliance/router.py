# (c) Copyright Datacraft, 2026
"""Compliance aggregation endpoints — auto-discovered by router_loader.

Routes
------
GET /compliance/stats    Aggregated compliance metrics for the current tenant
GET /compliance/alerts   Actionable compliance alerts sorted by severity
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.data_export.db.orm import DataExportJob
from papermerge.core.features.legal_hold.db.orm import LegalHold
from papermerge.core.features.retention.db.orm import RetentionPolicy
from papermerge.core.features.users.schema import User
from papermerge.core.utils.uuid_compat import uuid7str

_log = logging.getLogger(__name__)

router = APIRouter(
	prefix="/compliance",
	tags=["compliance"],
)


# ── I/O schemas ───────────────────────────────────────────────────────────────

class ComplianceStats(BaseModel):
	activePolicies: int
	documentsUnderRetention: int
	legalHoldsActive: int
	gdprRequestsPending: int
	gdprRequestsCompleted30d: int
	overdueRetentionActions: int
	nextRetentionDue: str | None = None  # ISO date string


class ComplianceAlert(BaseModel):
	id: str
	type: str  # overdue_retention | legal_hold_expiring | gdpr_deadline | audit_gap
	severity: str  # critical | warning | info
	message: str
	dueDate: str | None = None
	documentCount: int | None = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
	return datetime.now(tz=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
	if dt is None:
		return None
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=timezone.utc)
	return dt.isoformat()


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=ComplianceStats)
async def get_compliance_stats(
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> ComplianceStats:
	"""Return aggregated compliance metrics for the calling user's tenant."""
	tenant_id = str(user.tenant_id)
	now = _utcnow()
	thirty_days_ago = now - timedelta(days=30)

	# ── Retention policies ────────────────────────────────────────────────────

	policies_result = await db.execute(
		select(RetentionPolicy).where(
			RetentionPolicy.tenant_id == tenant_id,
		)
	)
	policies = policies_result.scalars().all()

	active_policies = [p for p in policies if p.is_active]
	active_count = len(active_policies)

	# Documents under retention: sum of docs_processed across active policies
	docs_under_retention = sum(p.docs_processed for p in active_policies)

	# Overdue: active policies that have never run OR last ran more than
	# after_days days ago (meaning the sweep window has elapsed again)
	overdue = 0
	next_due_dt: datetime | None = None

	for p in active_policies:
		if p.last_run_at is None:
			# Never run — treat as overdue from creation
			overdue += 1
		else:
			last_run = p.last_run_at
			if last_run.tzinfo is None:
				last_run = last_run.replace(tzinfo=timezone.utc)
			next_run = last_run + timedelta(days=p.after_days)
			if next_run <= now:
				overdue += 1
			else:
				if next_due_dt is None or next_run < next_due_dt:
					next_due_dt = next_run

	# ── Legal holds ───────────────────────────────────────────────────────────

	holds_result = await db.execute(
		select(func.count()).select_from(LegalHold).where(
			LegalHold.tenant_id == tenant_id,
			LegalHold.released_at.is_(None),
		)
	)
	legal_holds_active: int = holds_result.scalar_one()

	# ── GDPR / data export ────────────────────────────────────────────────────

	gdpr_pending_result = await db.execute(
		select(func.count()).select_from(DataExportJob).where(
			DataExportJob.tenant_id == tenant_id,
			DataExportJob.job_type == "gdpr_subject",
			DataExportJob.status.in_(["pending", "processing"]),
		)
	)
	gdpr_pending: int = gdpr_pending_result.scalar_one()

	gdpr_completed_result = await db.execute(
		select(func.count()).select_from(DataExportJob).where(
			DataExportJob.tenant_id == tenant_id,
			DataExportJob.job_type == "gdpr_subject",
			DataExportJob.status == "completed",
			DataExportJob.completed_at >= thirty_days_ago,
		)
	)
	gdpr_completed_30d: int = gdpr_completed_result.scalar_one()

	return ComplianceStats(
		activePolicies=active_count,
		documentsUnderRetention=docs_under_retention,
		legalHoldsActive=legal_holds_active,
		gdprRequestsPending=gdpr_pending,
		gdprRequestsCompleted30d=gdpr_completed_30d,
		overdueRetentionActions=overdue,
		nextRetentionDue=_iso(next_due_dt),
	)


@router.get("/alerts", response_model=list[ComplianceAlert])
async def get_compliance_alerts(
	user: Annotated[User, Depends(get_current_user)],
	db: AsyncSession = Depends(get_db),
) -> list[ComplianceAlert]:
	"""Return actionable compliance alerts for the calling user's tenant."""
	tenant_id = str(user.tenant_id)
	now = _utcnow()
	thirty_days_ago = now - timedelta(days=30)
	ninety_days_ago = now - timedelta(days=90)

	alerts: list[ComplianceAlert] = []

	# ── Overdue retention policies ────────────────────────────────────────────

	policies_result = await db.execute(
		select(RetentionPolicy).where(
			RetentionPolicy.tenant_id == tenant_id,
			RetentionPolicy.is_active.is_(True),
		)
	)
	active_policies = policies_result.scalars().all()

	overdue_count = 0
	for p in active_policies:
		if p.last_run_at is None:
			overdue_count += 1
		else:
			last_run = p.last_run_at
			if last_run.tzinfo is None:
				last_run = last_run.replace(tzinfo=timezone.utc)
			if last_run + timedelta(days=p.after_days) <= now:
				overdue_count += 1

	if overdue_count > 0:
		alerts.append(ComplianceAlert(
			id=uuid7str(),
			type="overdue_retention",
			severity="critical",
			message=f"{overdue_count} retention {'policy' if overdue_count == 1 else 'policies'} overdue — sweep has not run within the configured period.",
			documentCount=overdue_count,
		))

	# ── Legal holds older than 90 days ───────────────────────────────────────

	old_holds_result = await db.execute(
		select(func.count()).select_from(LegalHold).where(
			LegalHold.tenant_id == tenant_id,
			LegalHold.released_at.is_(None),
			LegalHold.held_at <= ninety_days_ago,
		)
	)
	old_holds: int = old_holds_result.scalar_one()

	if old_holds > 0:
		alerts.append(ComplianceAlert(
			id=uuid7str(),
			type="legal_hold_expiring",
			severity="warning",
			message=f"{old_holds} legal {'hold' if old_holds == 1 else 'holds'} active for more than 90 days — review whether they can be released.",
			documentCount=old_holds,
		))

	# ── GDPR requests pending > 30 days ──────────────────────────────────────

	stale_gdpr_result = await db.execute(
		select(func.count()).select_from(DataExportJob).where(
			DataExportJob.tenant_id == tenant_id,
			DataExportJob.job_type == "gdpr_subject",
			DataExportJob.status.in_(["pending", "processing"]),
			DataExportJob.created_at <= thirty_days_ago,
		)
	)
	stale_gdpr: int = stale_gdpr_result.scalar_one()

	if stale_gdpr > 0:
		alerts.append(ComplianceAlert(
			id=uuid7str(),
			type="gdpr_deadline",
			severity="critical",
			message=f"{stale_gdpr} GDPR subject {'request' if stale_gdpr == 1 else 'requests'} pending for over 30 days — GDPR Article 12 requires response within one month.",
			dueDate=_iso(thirty_days_ago),
			documentCount=stale_gdpr,
		))

	# ── Active GDPR requests (informational) ─────────────────────────────────

	all_gdpr_pending_result = await db.execute(
		select(func.count()).select_from(DataExportJob).where(
			DataExportJob.tenant_id == tenant_id,
			DataExportJob.job_type == "gdpr_subject",
			DataExportJob.status.in_(["pending", "processing"]),
			DataExportJob.created_at > thirty_days_ago,
		)
	)
	all_gdpr_pending: int = all_gdpr_pending_result.scalar_one()

	if all_gdpr_pending > 0:
		due = now + timedelta(days=30)
		alerts.append(ComplianceAlert(
			id=uuid7str(),
			type="gdpr_deadline",
			severity="info",
			message=f"{all_gdpr_pending} GDPR subject {'request' if all_gdpr_pending == 1 else 'requests'} in progress — respond before the 30-day deadline.",
			dueDate=_iso(due),
			documentCount=all_gdpr_pending,
		))

	return alerts
