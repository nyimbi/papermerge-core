# (c) Copyright Datacraft, 2026
"""QR code and document label endpoints.

Auto-discovered by papermerge.core.router_loader.discover_routers.

Routes:
  GET  /documents/{document_id}/qr-code          -> PNG image
  GET  /documents/{document_id}/label            -> PDF attachment
  POST /documents/batch-labels                   -> PDF attachment (multi-label)
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.config import get_settings
from papermerge.core.db.engine import get_db
from papermerge.core.features.auth import scopes
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.document.db.orm import Document
from papermerge.core.features.nodes.db.orm import Node

from .service import generate_batch_labels_pdf, generate_document_label_pdf, generate_qr_code

router = APIRouter(prefix="/documents", tags=["qr-labels"])

_log = logging.getLogger(__name__)
_settings = get_settings()


# ── helpers ───────────────────────────────────────────────────────────────────


async def _fetch_document(db: AsyncSession, document_id: UUID) -> Document:
	"""Return the Document ORM row or raise 404."""
	stmt = select(Document).where(Document.id == document_id)
	result = await db.execute(stmt)
	doc = result.scalar_one_or_none()
	if doc is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail=f"Document {document_id} not found",
		)
	return doc


# ── routes ────────────────────────────────────────────────────────────────────


@router.get(
	"/{document_id}/qr-code",
	response_class=Response,
	summary="Generate a QR code PNG for a document",
	responses={
		200: {"content": {"image/png": {}}, "description": "QR code PNG image"},
		404: {"description": "Document not found"},
	},
)
async def get_document_qr_code(
	document_id: UUID,
	size: int = Query(default=200, ge=21, le=2000, description="Image size in pixels (square)"),
	user: require_scopes(scopes.NODE_VIEW) = None,
	db: AsyncSession = Depends(get_db),
) -> Response:
	"""Return a PNG-encoded QR code whose payload is the document's public URL.

	Required scope: `node.view`
	"""
	await _fetch_document(db, document_id)

	qr_url = f"{_settings.app_base_url.rstrip('/')}/document/{document_id}"
	try:
		png_bytes = generate_qr_code(qr_url, size=size)
	except Exception as exc:
		_log.error("QR generation failed for %s: %s", document_id, exc, exc_info=True)
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail="QR code generation failed",
		)

	return Response(content=png_bytes, media_type="image/png")


@router.get(
	"/{document_id}/label",
	response_class=Response,
	summary="Generate a printable A6 label PDF for a document",
	responses={
		200: {"content": {"application/pdf": {}}, "description": "A6 label PDF"},
		404: {"description": "Document not found"},
	},
)
async def get_document_label(
	document_id: UUID,
	user: require_scopes(scopes.NODE_VIEW) = None,
	db: AsyncSession = Depends(get_db),
) -> Response:
	"""Return an A6 PDF label with QR code, title, ID, and creation date.

	Required scope: `node.view`
	"""
	doc = await _fetch_document(db, document_id)

	created_str = (
		doc.created_at.strftime("%Y-%m-%d %H:%M") if doc.created_at else ""
	)

	try:
		pdf_bytes = generate_document_label_pdf(
			document_id=str(document_id),
			title=doc.title or "Untitled",
			created_at=created_str,
			base_url=_settings.app_base_url,
		)
	except Exception as exc:
		_log.error("Label PDF generation failed for %s: %s", document_id, exc, exc_info=True)
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail="Label PDF generation failed",
		)

	return Response(
		content=pdf_bytes,
		media_type="application/pdf",
		headers={
			"Content-Disposition": f'attachment; filename="label-{document_id}.pdf"',
		},
	)


class BatchLabelsRequest(BaseModel):
	document_ids: list[str]


@router.post(
	"/batch-labels",
	response_class=Response,
	summary="Generate a combined PDF with labels for multiple documents",
	responses={
		200: {"content": {"application/pdf": {}}, "description": "Multi-label A4 PDF"},
	},
)
async def get_batch_labels(
	body: BatchLabelsRequest,
	user: require_scopes(scopes.NODE_VIEW) = None,
	db: AsyncSession = Depends(get_db),
) -> Response:
	"""Return an A4 PDF containing up to 2 A6 labels per page.

	The PDF is ready for printing on standard A6 or A4 paper stock.

	Required scope: `node.view`
	"""
	if not body.document_ids:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="document_ids must not be empty",
		)

	# Fetch all requested documents in one query
	uuids = []
	for raw_id in body.document_ids:
		try:
			uuids.append(UUID(raw_id))
		except ValueError:
			raise HTTPException(
				status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
				detail=f"Invalid document ID: {raw_id!r}",
			)

	stmt = select(Document).where(Document.id.in_(uuids))
	result = await db.execute(stmt)
	docs = {str(d.id): d for d in result.scalars().all()}

	labels = []
	for raw_id in body.document_ids:
		doc = docs.get(raw_id)
		if doc is None:
			_log.warning("batch-labels: document %s not found, skipping", raw_id)
			continue
		labels.append(
			{
				"document_id": raw_id,
				"title": doc.title or "Untitled",
				"created_at": (
					doc.created_at.strftime("%Y-%m-%d %H:%M")
					if doc.created_at
					else ""
				),
			}
		)

	if not labels:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="None of the requested documents were found",
		)

	try:
		pdf_bytes = generate_batch_labels_pdf(labels, base_url=_settings.app_base_url)
	except Exception as exc:
		_log.error("Batch label PDF generation failed: %s", exc, exc_info=True)
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail="Batch label PDF generation failed",
		)

	return Response(
		content=pdf_bytes,
		media_type="application/pdf",
		headers={
			"Content-Disposition": 'attachment; filename="batch-labels.pdf"',
		},
	)
