# (c) Copyright Datacraft, 2026
"""Batch status updates, split/merge, and barcode label generation."""
import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core import orm as core_orm
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.features.users.schema import User
from papermerge.core.utils.uuid_compat import uuid7str
from .models import ScanningBatchModel, ScanningBatchDocumentModel, ScanningProjectModel

router = APIRouter(
	prefix="/scanning-projects",
	tags=["scanning-projects-batch-ops"],
)

_log = logging.getLogger(__name__)

_VALID_KANBAN_STATUSES = {"unassigned", "in_progress", "qc", "complete"}


class _BatchStatusUpdate(BaseModel):
	status: str


@router.patch("/batches/{batch_id}/status")
async def update_batch_status(
	batch_id: str,
	body: _BatchStatusUpdate,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_UPDATE))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
	"""Update batch Kanban status (unassigned → in_progress → qc → complete)."""
	if body.status not in _VALID_KANBAN_STATUSES:
		raise HTTPException(
			status_code=422,
			detail=f"status must be one of {sorted(_VALID_KANBAN_STATUSES)}",
		)

	row = await db.execute(select(ScanningBatchModel).where(ScanningBatchModel.id == batch_id))
	batch = row.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	batch.status = body.status
	await db.commit()

	if body.status in ("quality_check", "complete"):
		try:
			from papermerge.core.tasks import send_task
			send_task(
				"darchiva.quality.assess_batch",
				kwargs={"batch_id": batch_id},
			)
			_log.info("Queued quality assessment for batch %s (status=%s)", batch_id, body.status)
		except Exception as exc:
			_log.warning("Failed to queue quality assessment for batch %s: %s", batch_id, exc)

	return {"id": batch_id, "status": body.status}


class _MergeBatchesBody(BaseModel):
	source_batch_ids: list[str]
	target_batch_id: str


@router.post("/batches/{batch_id}/split")
async def split_batch(
	batch_id: str,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_UPDATE))],
	db: Annotated[AsyncSession, Depends(get_db)],
	at_document_index: int = Query(..., ge=1, description="Split after this 0-based position (must be ≥ 1)"),
) -> dict:
	"""Split a batch into two at the given document index (0-based).

	Documents at positions < at_document_index stay in the original batch.
	Documents at positions >= at_document_index move to a new batch.
	"""
	row = await db.execute(select(ScanningBatchModel).where(ScanningBatchModel.id == batch_id))
	batch = row.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	doc_rows = await db.execute(
		select(ScanningBatchDocumentModel)
		.where(ScanningBatchDocumentModel.batch_id == batch_id)
		.order_by(ScanningBatchDocumentModel.page_number)
	)
	docs = doc_rows.scalars().all()

	if at_document_index < 1 or at_document_index >= len(docs):
		raise HTTPException(
			status_code=422,
			detail=f"at_document_index must be between 1 and {len(docs) - 1} (batch has {len(docs)} documents)",
		)

	new_batch_id = uuid7str()
	new_batch = ScanningBatchModel(
		id=new_batch_id,
		project_id=batch.project_id,
		batch_number=f"{batch.batch_number}-B",
		type=batch.type,
		physical_location=batch.physical_location,
		status="pending",
		notes=f"Split from batch {batch_id}",
		estimated_pages=0,
		actual_pages=0,
		scanned_pages=0,
	)
	db.add(new_batch)
	await db.flush()  # get new_batch.id into session before FK updates

	to_move = docs[at_document_index:]
	for doc in to_move:
		doc.batch_id = UUID(new_batch_id)  # type: ignore[assignment]

	original_count = at_document_index
	new_count = len(to_move)

	batch.actual_pages = original_count
	batch.scanned_pages = original_count
	new_batch.actual_pages = new_count
	new_batch.scanned_pages = new_count

	# Audit log
	now = datetime.utcnow()
	db.add(core_orm.AuditLog(
		table_name="scanning_batches",
		record_id=UUID(batch_id),
		operation="UPDATE",
		user_id=UUID(str(user.id)),
		username=getattr(user, "username", None),
		application="api",
		audit_message=f"Batch split at index {at_document_index}: {original_count} docs remain, {new_count} moved to {new_batch_id}",
		timestamp=now,
	))

	await db.commit()

	_log.info(
		"Batch %s split at index %d: %d docs retained, %d moved to new batch %s (user=%s)",
		batch_id, at_document_index, original_count, new_count, new_batch_id, user.id,
	)

	return {
		"original_batch_id": batch_id,
		"new_batch_id": new_batch_id,
		"original_count": original_count,
		"new_count": new_count,
	}


@router.post("/batches/merge")
async def merge_batches(
	body: _MergeBatchesBody,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_UPDATE))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
	"""Merge multiple batches into one target batch.

	All batches in source_batch_ids must belong to the same project.
	target_batch_id must be one of the source_batch_ids — it is the survivor.
	The other source batches are emptied and deleted.
	"""
	if body.target_batch_id not in body.source_batch_ids:
		raise HTTPException(
			status_code=422,
			detail="target_batch_id must be one of source_batch_ids",
		)
	if len(body.source_batch_ids) < 2:
		raise HTTPException(status_code=422, detail="Provide at least 2 source_batch_ids to merge")

	# Load all source batches
	rows = await db.execute(
		select(ScanningBatchModel).where(ScanningBatchModel.id.in_(body.source_batch_ids))
	)
	batches = {str(b.id): b for b in rows.scalars().all()}

	missing = set(body.source_batch_ids) - set(batches)
	if missing:
		raise HTTPException(status_code=404, detail=f"Batches not found: {sorted(missing)}")

	project_ids = {str(b.project_id) for b in batches.values()}
	if len(project_ids) > 1:
		raise HTTPException(
			status_code=422,
			detail="All batches must belong to the same project",
		)

	target = batches[body.target_batch_id]
	sources_to_delete = [b for bid, b in batches.items() if bid != body.target_batch_id]

	# Reassign all documents from source batches to target
	total_moved = 0
	for src in sources_to_delete:
		doc_rows = await db.execute(
			select(ScanningBatchDocumentModel)
			.where(ScanningBatchDocumentModel.batch_id == src.id)
			.order_by(ScanningBatchDocumentModel.page_number)
		)
		src_docs = doc_rows.scalars().all()
		total_moved += len(src_docs)

		# Find highest page_number already in target to append after
		max_page_row = await db.execute(
			select(func.max(ScanningBatchDocumentModel.page_number))
			.where(ScanningBatchDocumentModel.batch_id == target.id)
		)
		max_page: int = max_page_row.scalar() or 0

		for offset, doc in enumerate(src_docs, start=1):
			doc.batch_id = target.id
			doc.page_number = max_page + offset

		await db.delete(src)

	# Recount target
	target_doc_count_row = await db.execute(
		select(func.count()).select_from(ScanningBatchDocumentModel)
		.where(ScanningBatchDocumentModel.batch_id == target.id)
	)
	target_total = target_doc_count_row.scalar() or 0
	target.actual_pages = target_total
	target.scanned_pages = target_total

	# Audit log
	merged_from_ids = [str(b.id) for b in sources_to_delete]
	now = datetime.utcnow()
	db.add(core_orm.AuditLog(
		table_name="scanning_batches",
		record_id=target.id,
		operation="UPDATE",
		user_id=UUID(str(user.id)),
		username=getattr(user, "username", None),
		application="api",
		audit_message=f"Merged {len(sources_to_delete)} batch(es) into {body.target_batch_id}: absorbed from {merged_from_ids}",
		timestamp=now,
	))

	await db.commit()

	_log.info(
		"Batches %s merged into %s (%d docs total, user=%s)",
		merged_from_ids, body.target_batch_id, target_total, user.id,
	)

	return {
		"merged_into": body.target_batch_id,
		"merged_from": merged_from_ids,
		"total_documents": target_total,
	}


@router.post("/{project_id}/barcode-labels")
async def generate_barcode_labels(
	project_id: str,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
	count: int = Query(default=20, ge=1, le=200),
	prefix: str = Query(default=""),
) -> HTMLResponse:
	"""Generate a printable HTML page with barcode separator labels."""
	row = await db.execute(select(ScanningProjectModel).where(ScanningProjectModel.id == project_id))
	project = row.scalar_one_or_none()
	if not project:
		raise HTTPException(status_code=404, detail="Project not found")

	code = getattr(project, "code", project_id[:8].upper())
	pfx = prefix.upper().strip()

	labels: list[str] = []
	for n in range(1, count + 1):
		barcode_str = f"{code}-{pfx}{n:06d}" if pfx else f"{code}-{n:06d}"
		labels.append(barcode_str)

	# Build printable HTML grid — 3 columns × 10 rows per page
	cells = "\n".join(
		f'<div class="label"><pre class="barcode">{lbl}</pre><span class="human">{lbl}</span></div>'
		for lbl in labels
	)

	html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{code} Barcode Labels</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Courier New', monospace; background: #fff; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; padding: 8px; }}
  .label {{
    border: 1px solid #555; padding: 6px 8px; height: 60px;
    display: flex; flex-direction: column; justify-content: center; align-items: center;
    overflow: hidden;
  }}
  .barcode {{
    font-size: 11px; font-weight: bold; letter-spacing: 2px;
    border-bottom: 3px solid #000; padding-bottom: 2px; width: 100%; text-align: center;
  }}
  .human {{ font-size: 9px; margin-top: 3px; color: #333; }}
  @media print {{
    body {{ margin: 0; }}
    .grid {{ gap: 2px; padding: 4px; }}
    @page {{ margin: 10mm; }}
  }}
</style>
</head>
<body>
<div class="grid">{cells}</div>
<script>window.print();</script>
</body>
</html>"""

	return HTMLResponse(
		content=html,
		headers={"Content-Disposition": f'attachment; filename="{code}-labels.html"'},
	)
