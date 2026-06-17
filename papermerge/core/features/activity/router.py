# (c) Copyright Datacraft, 2026
"""Document Activity Feed and Recent Changes Timeline.

Auto-discovered by router_loader — exports `router`.
"""
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_, String as SAString, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes

router = APIRouter(
	prefix="/activity",
	tags=["activity"],
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Response schema
# ─────────────────────────────────────────────────────────────────────────────

class ActivityEvent(BaseModel):
	event_type: str
	actor_name: str | None
	actor_id: str | None
	description: str
	timestamp: datetime | None
	data: dict[str, Any] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_TABLE_EVENT_TYPES: dict[str, str] = {
	"nodes": "document.created",
	"documents": "document.created",
	"document_versions": "document.version_added",
	"ocr_tasks": "document.ocr_complete",
	"document_type_assignments": "document.classified",
	"folder_moves": "document.moved",
	"node_moves": "document.moved",
	"tags": "document.tagged",
	"document_tags": "document.tagged",
	"document_signature_requests": "document.signed",
	"approval_workflows": "document.approved",
	"document_annotations": "document.annotated",
	"legal_hold_entries": "document.held",
}


def _infer_event_type(table_name: str, operation: str) -> str:
	"""Map table_name + operation to a semantic event_type string."""
	mapped = _TABLE_EVENT_TYPES.get(table_name)
	if mapped:
		return mapped
	# Fallback: table_name.operation
	return f"{table_name}.{operation.lower()}"


def _build_description(event_type: str, actor_name: str | None, new_values: dict | None) -> str:
	actor = actor_name or "System"
	match event_type:
		case "document.created":
			return f"Created by {actor}"
		case "document.version_added":
			return f"New version uploaded by {actor}"
		case "document.ocr_complete":
			return "OCR completed"
		case "document.classified":
			doc_type = (new_values or {}).get("document_type_name") or (new_values or {}).get("name")
			if doc_type:
				return f"Classified as {doc_type}"
			return f"Document classified by {actor}"
		case "document.moved":
			return f"Moved by {actor}"
		case "document.tagged":
			tag = (new_values or {}).get("label") or (new_values or {}).get("name")
			if tag:
				return f"Tagged '{tag}' by {actor}"
			return f"Tag applied by {actor}"
		case "document.signed":
			return f"Signature requested by {actor}"
		case "document.approved":
			status = (new_values or {}).get("status")
			if status == "approved":
				return f"Approved by {actor}"
			elif status == "rejected":
				return f"Rejected by {actor}"
			return f"Approval workflow started by {actor}"
		case "document.annotated":
			ann_type = (new_values or {}).get("annotation_type", "")
			if ann_type:
				return f"{ann_type.capitalize()} annotation added by {actor}"
			return f"Annotation added by {actor}"
		case "document.held":
			hold_name = (new_values or {}).get("hold_name")
			if hold_name:
				return f"Legal hold '{hold_name}' placed by {actor}"
			return f"Legal hold placed by {actor}"
		case _:
			return f"{event_type.replace('.', ' ').replace('_', ' ').title()} by {actor}"


# ─────────────────────────────────────────────────────────────────────────────
# GET /documents/{document_id}/activity
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/documents/{document_id}/activity", response_model=list[ActivityEvent])
async def get_document_activity(
	document_id: uuid.UUID,
	user: require_scopes(scopes.NODE_VIEW),
	limit: int = Query(50, ge=1, le=200),
	db_session: AsyncSession = Depends(get_db),
) -> list[ActivityEvent]:
	"""Aggregated activity timeline for a single document.

	Pulls from audit_log (filtered by record_id == document_id), plus
	dedicated tables: signatures, approval workflows, annotations, legal holds.
	Returns events ordered by timestamp descending.
	"""
	from papermerge.core.features.audit.db.orm import AuditLog

	doc_id_str = str(document_id)
	events: list[ActivityEvent] = []

	# ── 1. audit_log rows whose record_id matches the document ───────────────
	try:
		stmt = (
			select(AuditLog)
			.where(
				or_(
					AuditLog.record_id == document_id,
					# Some rows store doc id in new_values.document_id (JSON)
					func.cast(AuditLog.new_values["document_id"].astext, SAString) == doc_id_str,
				)
			)
			.order_by(AuditLog.timestamp.desc())
			.limit(limit)
		)
		result = await db_session.execute(stmt)
		for row in result.scalars().all():
			op = str(row.operation.value if hasattr(row.operation, "value") else row.operation)
			event_type = _infer_event_type(row.table_name or "", op)
			events.append(ActivityEvent(
				event_type=event_type,
				actor_name=row.username,
				actor_id=str(row.user_id) if row.user_id else None,
				description=_build_description(event_type, row.username, row.new_values),
				timestamp=row.timestamp,
				data={
					"table_name": row.table_name,
					"operation": op,
					"changed_fields": row.changed_fields,
					"audit_message": row.audit_message,
				},
			))
	except Exception:
		logger.exception("audit_log query failed for document %s", document_id)

	# ── 2. document_signature_requests ───────────────────────────────────────
	try:
		from papermerge.core.features.signatures.db.orm import DocumentSignatureRequest
		sig_stmt = (
			select(DocumentSignatureRequest)
			.where(DocumentSignatureRequest.document_id == doc_id_str)
			.order_by(DocumentSignatureRequest.signed_at.desc().nullslast())
		)
		sig_result = await db_session.execute(sig_stmt)
		for sig in sig_result.scalars().all():
			ts = sig.signed_at or sig.declined_at
			status_label = {"signed": "Signed", "declined": "Declined", "pending": "Signature requested"}.get(
				sig.status, "Signature requested"
			)
			events.append(ActivityEvent(
				event_type="document.signed",
				actor_name=sig.requested_from_name or sig.requested_from_email,
				actor_id=sig.requested_by_id,
				description=f"{status_label} by {sig.requested_from_name or sig.requested_from_email}",
				timestamp=ts,
				data={"status": sig.status, "signer_email": sig.requested_from_email},
			))
	except Exception:
		logger.debug("signature_requests not available for doc %s", document_id)

	# ── 3. approval_workflows ─────────────────────────────────────────────────
	try:
		from papermerge.core.features.approvals.db.orm import ApprovalWorkflow
		appr_stmt = (
			select(ApprovalWorkflow)
			.where(ApprovalWorkflow.document_id == doc_id_str)
			.order_by(ApprovalWorkflow.created_at.desc())
		)
		appr_result = await db_session.execute(appr_stmt)
		for wf in appr_result.scalars().all():
			status_label = {"approved": "Approved", "rejected": "Rejected", "in_review": "Approval started"}.get(
				wf.status, "Approval workflow"
			)
			events.append(ActivityEvent(
				event_type="document.approved",
				actor_name=None,
				actor_id=wf.created_by_id,
				description=f"{status_label} — {wf.name}",
				timestamp=wf.completed_at or wf.created_at,
				data={"workflow_name": wf.name, "status": wf.status},
			))
	except Exception:
		logger.debug("approval_workflows not available for doc %s", document_id)

	# ── 4. document_annotations ───────────────────────────────────────────────
	try:
		from papermerge.core.features.annotations.db.orm import DocumentAnnotation
		ann_stmt = (
			select(DocumentAnnotation)
			.where(DocumentAnnotation.document_id == document_id)
			.order_by(DocumentAnnotation.created_at.desc())
		)
		ann_result = await db_session.execute(ann_stmt)
		for ann in ann_result.scalars().all():
			events.append(ActivityEvent(
				event_type="document.annotated",
				actor_name=ann.created_by_id,
				actor_id=ann.created_by_id,
				description=_build_description("document.annotated", ann.created_by_id, {"annotation_type": ann.annotation_type}),
				timestamp=ann.created_at,
				data={"annotation_type": ann.annotation_type, "page": ann.page_number},
			))
	except Exception:
		logger.debug("annotations not available for doc %s", document_id)

	# ── 5. legal_hold_entries ─────────────────────────────────────────────────
	try:
		from papermerge.core.features.legal_hold.db.orm import LegalHold
		hold_stmt = (
			select(LegalHold)
			.where(LegalHold.document_id == doc_id_str)
			.order_by(LegalHold.held_at.desc())
		)
		hold_result = await db_session.execute(hold_stmt)
		for hold in hold_result.scalars().all():
			events.append(ActivityEvent(
				event_type="document.held",
				actor_name=hold.held_by_id,
				actor_id=hold.held_by_id,
				description=_build_description("document.held", hold.held_by_id, {"hold_name": hold.hold_name}),
				timestamp=hold.held_at,
				data={"hold_name": hold.hold_name, "released": hold.released_at is not None},
			))
	except Exception:
		logger.debug("legal_hold_entries not available for doc %s", document_id)

	# Sort all sources by timestamp desc and cap at limit
	events.sort(key=lambda e: e.timestamp or datetime.min, reverse=True)
	return events[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# GET /activity/feed
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/feed", response_model=list[ActivityEvent])
async def get_activity_feed(
	user: require_scopes(scopes.NODE_VIEW),
	limit: int = Query(30, ge=1, le=100),
	db_session: AsyncSession = Depends(get_db),
) -> list[ActivityEvent]:
	"""Personal activity feed — all audit events for the current user, newest first."""
	from papermerge.core.features.audit.db.orm import AuditLog

	try:
		stmt = (
			select(AuditLog)
			.where(AuditLog.user_id == user.id)
			.order_by(AuditLog.timestamp.desc())
			.limit(limit)
		)
		result = await db_session.execute(stmt)
		events: list[ActivityEvent] = []
		for row in result.scalars().all():
			op = str(row.operation.value if hasattr(row.operation, "value") else row.operation)
			event_type = _infer_event_type(row.table_name or "", op)
			events.append(ActivityEvent(
				event_type=event_type,
				actor_name=row.username,
				actor_id=str(row.user_id) if row.user_id else None,
				description=_build_description(event_type, row.username, row.new_values),
				timestamp=row.timestamp,
				data={
					"table_name": row.table_name,
					"record_id": str(row.record_id) if row.record_id else None,
					"operation": op,
				},
			))
		return events
	except Exception:
		logger.exception("Failed to fetch activity feed for user %s", user.id)
		return []
