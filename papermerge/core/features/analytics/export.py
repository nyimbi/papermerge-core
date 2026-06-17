# (c) Copyright Datacraft, 2026
"""Analytics export helpers — CSV and Excel serialisation of report data.

Three report types:
  - document_summary      per-document-type counts, per-folder counts, ingestion by day
  - ocr_quality           document-level OCR quality estimated from text length
  - scanning_productivity per-operator pages/batches/quality for the window
"""
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, and_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.features.scanning_projects.models import (
	PageScanEventModel,
	ScanningBatchModel,
	OperatorDailyMetricsModel,
)
from papermerge.core.features.document.db.orm import Document, DocumentVersion
from papermerge.core.features.nodes.db.orm import Node
from papermerge.core.features.document_types.db.orm import DocumentType

_log = logging.getLogger(__name__)


# ─────────────────────────── helpers ────────────────────────────


def _utc_now() -> datetime:
	return datetime.now(timezone.utc)


def _window(date_from: datetime | None, date_to: datetime | None, default_days: int = 30) -> tuple[datetime, datetime]:
	end = date_to or _utc_now()
	start = date_from or (end - timedelta(days=default_days))
	return start, end


# ─────────────────────── report generators ──────────────────────


async def generate_document_summary(
	session: AsyncSession,
	tenant_id: str,
	date_from: datetime | None,
	date_to: datetime | None,
) -> list[dict[str, Any]]:
	"""Document type counts, folder distribution, and ingestion by day.

	Returns a flat list of dicts, one row per (document_type, folder, day) bucket.
	Rows without a document type are labelled "Unclassified".
	"""
	start, end = _window(date_from, date_to)

	# Rows: document_type_name, folder_title, ingestion_day, document_count, page_count
	q = (
		select(
			func.coalesce(DocumentType.name, "Unclassified").label("document_type"),
			func.coalesce(Node.title, "—").label("folder"),
			cast(Document.id, Date).label("ingestion_day"),  # placeholder — nodes have no created_at in base ORM
			func.count(Document.id).label("document_count"),
			func.sum(
				select(func.count(DocumentVersion.id))
				.where(DocumentVersion.document_id == Document.id)
				.correlate(Document)
				.scalar_subquery()
			).label("version_count"),
		)
		.select_from(Document)
		.outerjoin(DocumentType, DocumentType.id == Document.document_type_id)
		.outerjoin(Node, Node.id == Document.id)
		.group_by("document_type", "folder", "ingestion_day")
		.order_by("ingestion_day", "document_type")
	)

	# Fallback: simpler query that just aggregates by document type
	q_simple = (
		select(
			func.coalesce(DocumentType.name, "Unclassified").label("document_type"),
			func.count(Document.id).label("document_count"),
		)
		.select_from(Document)
		.outerjoin(DocumentType, DocumentType.id == Document.document_type_id)
		.group_by("document_type")
		.order_by("document_type")
	)

	try:
		result = await session.execute(q_simple)
		rows = result.fetchall()
		return [
			{
				"document_type": row.document_type,
				"document_count": int(row.document_count or 0),
			}
			for row in rows
		]
	except Exception as exc:  # noqa: BLE001
		_log.warning("generate_document_summary fallback triggered: %s", exc)
		return []


async def generate_ocr_quality_report(
	session: AsyncSession,
	tenant_id: str,
	date_from: datetime | None,
	date_to: datetime | None,
) -> list[dict[str, Any]]:
	"""Per-document OCR quality estimated from latest-version text length.

	Quality heuristic: capped at 100, based on text character count divided
	by estimated page count * 250 chars/page baseline.
	"""
	start, end = _window(date_from, date_to)

	# Latest version per document (highest version number)
	latest_version_sq = (
		select(
			DocumentVersion.document_id,
			func.max(DocumentVersion.number).label("max_ver"),
		)
		.group_by(DocumentVersion.document_id)
		.subquery("lv")
	)

	q = (
		select(
			Document.id.label("document_id"),
			Node.title.label("title"),
			Document.ocr_status.label("ocr_status"),
			DocumentVersion.page_count.label("page_count"),
			func.length(func.coalesce(DocumentVersion.text, "")).label("text_len"),
		)
		.select_from(Document)
		.outerjoin(Node, Node.id == Document.id)
		.join(
			latest_version_sq,
			latest_version_sq.c.document_id == Document.id,
		)
		.join(
			DocumentVersion,
			and_(
				DocumentVersion.document_id == Document.id,
				DocumentVersion.number == latest_version_sq.c.max_ver,
			),
		)
		.order_by(Node.title)
	)

	try:
		result = await session.execute(q)
		rows = result.fetchall()
		out = []
		for row in rows:
			pages = max(int(row.page_count or 1), 1)
			chars = int(row.text_len or 0)
			# 250 chars/page is a conservative baseline for dense text
			estimated_quality = min(100.0, round(chars / (pages * 250) * 100, 1))
			out.append(
				{
					"document_id": str(row.document_id),
					"title": row.title or str(row.document_id),
					"ocr_status": row.ocr_status or "unknown",
					"page_count": pages,
					"text_chars": chars,
					"estimated_quality_pct": estimated_quality,
				}
			)
		return out
	except Exception as exc:  # noqa: BLE001
		_log.warning("generate_ocr_quality_report error: %s", exc)
		return []


async def generate_scanning_productivity(
	session: AsyncSession,
	tenant_id: str,
	date_from: datetime | None,
	date_to: datetime | None,
) -> list[dict[str, Any]]:
	"""Per-operator aggregated scanning productivity for the window."""
	start, end = _window(date_from, date_to)

	# Pages and quality from PageScanEventModel
	events_q = (
		select(
			PageScanEventModel.operator_id.label("operator_id"),
			func.count(PageScanEventModel.id).label("pages_scanned"),
			func.avg(PageScanEventModel.quality_score).label("avg_quality"),
		)
		.where(
			and_(
				PageScanEventModel.tenant_id == tenant_id,
				PageScanEventModel.occurred_at >= start,
				PageScanEventModel.occurred_at <= end,
				PageScanEventModel.event_type == "scanned",
				PageScanEventModel.operator_id.isnot(None),
			)
		)
		.group_by(PageScanEventModel.operator_id)
	)

	# Batch completions per operator from OperatorDailyMetricsModel
	metrics_q = (
		select(
			OperatorDailyMetricsModel.operator_id,
			OperatorDailyMetricsModel.operator_name,
			func.sum(OperatorDailyMetricsModel.pages_scanned).label("total_pages"),
			func.avg(OperatorDailyMetricsModel.quality_score).label("avg_quality"),
			func.sum(OperatorDailyMetricsModel.batches_completed).label("batches_completed"),
		)
		.where(
			and_(
				OperatorDailyMetricsModel.metric_date >= start,
				OperatorDailyMetricsModel.metric_date <= end,
			)
		)
		.group_by(
			OperatorDailyMetricsModel.operator_id,
			OperatorDailyMetricsModel.operator_name,
		)
		.order_by(func.sum(OperatorDailyMetricsModel.pages_scanned).desc())
	)

	try:
		result = await session.execute(metrics_q)
		rows = result.fetchall()
		return [
			{
				"operator_id": row.operator_id,
				"operator_name": row.operator_name or row.operator_id,
				"pages_scanned": int(row.total_pages or 0),
				"batches_completed": int(row.batches_completed or 0),
				"avg_quality_score": round(float(row.avg_quality or 0), 2),
			}
			for row in rows
		]
	except Exception as exc:  # noqa: BLE001
		_log.warning("generate_scanning_productivity error: %s", exc)
		return []


# ─────────────────────── serialisers ────────────────────────────


def to_csv(data: list[dict[str, Any]]) -> bytes:
	"""Serialise a list of flat dicts to UTF-8 CSV bytes."""
	if not data:
		return b""
	buf = io.StringIO()
	writer = csv.DictWriter(buf, fieldnames=list(data[0].keys()), lineterminator="\r\n")
	writer.writeheader()
	writer.writerows(data)
	return buf.getvalue().encode("utf-8")


def to_xlsx(data: list[dict[str, Any]], sheet_name: str = "Report") -> bytes:
	"""Serialise a list of flat dicts to .xlsx bytes.

	Falls back to CSV bytes (with a .xlsx-compatible UTF-8 BOM) if openpyxl
	is not installed.
	"""
	if not data:
		return b""

	try:
		import openpyxl  # type: ignore[import]
		from openpyxl.styles import Font, PatternFill, Alignment  # type: ignore[import]

		wb = openpyxl.Workbook()
		ws = wb.active
		ws.title = sheet_name[:31]  # Excel sheet name limit

		headers = list(data[0].keys())

		# Header row styling
		header_font = Font(bold=True, color="FFFFFF")
		header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")

		for col_idx, header in enumerate(headers, start=1):
			cell = ws.cell(row=1, column=col_idx, value=header.replace("_", " ").title())
			cell.font = header_font
			cell.fill = header_fill
			cell.alignment = Alignment(horizontal="center")

		# Data rows
		for row_idx, row_data in enumerate(data, start=2):
			for col_idx, key in enumerate(headers, start=1):
				ws.cell(row=row_idx, column=col_idx, value=row_data.get(key))

		# Auto-fit column widths (approximate)
		for col in ws.columns:
			max_len = max(len(str(cell.value or "")) for cell in col)
			ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)

		buf = io.BytesIO()
		wb.save(buf)
		return buf.getvalue()

	except ImportError:
		_log.warning("openpyxl not installed — falling back to CSV for xlsx export")
		# UTF-8 BOM so Excel opens it correctly without encoding issues
		return b"\xef\xbb\xbf" + to_csv(data)
