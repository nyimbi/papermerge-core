# (c) Copyright Datacraft, 2026
"""Batch status updates and barcode label generation."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.features.users.schema import User
from .models import ScanningBatchModel, ScanningProjectModel

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
