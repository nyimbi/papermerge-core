# (c) Copyright Datacraft, 2026
"""Analytics export router — auto-discovered by router_loader as router_export.py.

GET /analytics/export
  Query params:
    format   csv | xlsx          (default: csv)
    report   document_summary | ocr_quality | scanning_productivity
    date_from  ISO-8601 datetime (optional)
    date_to    ISO-8601 datetime (optional)

Returns a StreamingResponse with Content-Disposition attachment.
"""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.schema import User
from papermerge.core.features.analytics.export import (
	generate_document_summary,
	generate_ocr_quality_report,
	generate_scanning_productivity,
	to_csv,
	to_xlsx,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

ReportType = Literal["document_summary", "ocr_quality", "scanning_productivity"]
FormatType = Literal["csv", "xlsx"]

_REPORT_LABELS: dict[str, str] = {
	"document_summary": "document-summary",
	"ocr_quality": "ocr-quality",
	"scanning_productivity": "scanning-productivity",
}


@router.get("/export")
async def export_analytics(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	report: ReportType = Query(default="document_summary"),
	format: FormatType = Query(default="csv"),
	date_from: datetime | None = Query(default=None),
	date_to: datetime | None = Query(default=None),
):
	"""Download an analytics report as CSV or Excel.

	The three report types correspond to the three data generators in export.py.
	Date window defaults to the last 30 days when omitted.
	"""
	tenant_id = str(user.tenant_id)

	if report == "document_summary":
		data = await generate_document_summary(session, tenant_id, date_from, date_to)
	elif report == "ocr_quality":
		data = await generate_ocr_quality_report(session, tenant_id, date_from, date_to)
	elif report == "scanning_productivity":
		data = await generate_scanning_productivity(session, tenant_id, date_from, date_to)
	else:
		raise HTTPException(status_code=400, detail=f"Unknown report type: {report}")

	label = _REPORT_LABELS.get(report, report)

	if format == "xlsx":
		content = to_xlsx(data, sheet_name=label.replace("-", " ").title())
		media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
		filename = f"{label}.xlsx"
	else:
		content = to_csv(data)
		media_type = "text/csv"
		filename = f"{label}.csv"

	if not content:
		# Return an empty file rather than a 404 — the date window just has no data
		content = b""

	return StreamingResponse(
		iter([content]),
		media_type=media_type,
		headers={
			"Content-Disposition": f'attachment; filename="{filename}"',
			"Content-Length": str(len(content)),
		},
	)
