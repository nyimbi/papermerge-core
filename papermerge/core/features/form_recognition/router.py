# (c) Copyright Datacraft, 2026
"""Form recognition API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.services.form_recognition import FormRecognitionService
from . import schema
from .db.orm import FormTemplate, FormField, FormExtraction, ExtractedFieldValue, Signature

router = APIRouter(
	prefix="/forms",
	tags=["forms"],
)

logger = logging.getLogger(__name__)


@router.get("/templates")
async def list_templates(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	category: str | None = None,
	page: int = 1,
	page_size: int = 20,
) -> schema.TemplateListResponse:
	"""List form templates."""
	offset = (page - 1) * page_size

	conditions = [
		FormTemplate.tenant_id == user.tenant_id,
	]
	if category:
		conditions.append(FormTemplate.category == category)

	count_stmt = select(func.count()).select_from(FormTemplate).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(FormTemplate).where(and_(*conditions)).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	templates = result.scalars().all()

	return schema.TemplateListResponse(
		items=[schema.TemplateInfo.from_orm_template(t) for t in templates],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/templates")
async def create_template(
	template: schema.TemplateCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TemplateInfo:
	"""Create a form template."""
	service = FormRecognitionService(db_session)

	result = await service.create_template(
		tenant_id=user.tenant_id,
		name=template.name,
		category=template.category,
		fields=template.fields,
		is_multipage=template.is_multipage,
		page_count=template.page_count,
	)

	return schema.TemplateInfo.from_orm_template(result)


@router.get("/templates/{template_id}")
async def get_template(
	template_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TemplateDetail:
	"""Get template details with fields."""
	template = await db_session.get(FormTemplate, template_id)
	if not template:
		raise HTTPException(status_code=404, detail="Template not found")

	# ORM FormField has no `order` column — order by page_number, then name.
	stmt = (
		select(FormField)
		.where(FormField.template_id == template_id)
		.order_by(FormField.page_number, FormField.name)
	)
	result = await db_session.execute(stmt)
	fields = result.scalars().all()

	return schema.TemplateDetail(
		id=template.id,
		name=template.name,
		category=template.category,
		# ORM has no is_multipage column; derive from page_count.
		is_multipage=template.page_count > 1,
		page_count=template.page_count,
		# ORM has no is_active column; all stored templates are considered active.
		is_active=True,
		fields=[
			schema.FieldInfo(
				id=f.id,
				name=f.name,
				field_type=f.field_type,
				label=f.label,
				page_number=f.page_number,
				# ORM column is `required`, schema field is `is_required`.
				is_required=f.required,
			)
			for f in fields
		],
	)


@router.post("/extract")
async def extract_form_data(
	request: schema.ExtractionRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.ExtractionResponse:
	"""Extract form data from a document."""
	from papermerge.core.tasks import send_task

	# Check for an existing pending/processing extraction to avoid duplicates
	existing_stmt = (
		select(FormExtraction)
		.where(
			FormExtraction.document_id == request.document_id,
			FormExtraction.status.in_(["pending", "processing"]),
		)
	)
	existing = (await db_session.execute(existing_stmt)).scalar()
	if existing:
		return schema.ExtractionResponse(
			success=True,
			message="Extraction already in progress",
			document_id=request.document_id,
		)

	# Create DB record synchronously so GET /extractions/{doc_id} can track status
	extraction = FormExtraction(
		document_id=request.document_id,
		template_id=request.template_id,
		status="pending",
	)
	db_session.add(extraction)
	await db_session.commit()

	send_task(
		"darchiva.form.process",
		kwargs={
			"document_id": str(request.document_id),
			"template_id": str(request.template_id) if request.template_id else None,
			"tenant_id": str(user.tenant_id),
		},
	)

	return schema.ExtractionResponse(
		success=True,
		message="Form extraction queued",
		document_id=request.document_id,
	)


@router.get("/extractions/{document_id}")
async def get_extraction_results(
	document_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.ExtractionResult:
	"""Get form extraction results for a document."""
	stmt = (
		select(FormExtraction)
		.where(FormExtraction.document_id == document_id)
		.order_by(FormExtraction.created_at.desc())
	)
	result = await db_session.execute(stmt)
	extraction = result.scalar()

	if not extraction:
		raise HTTPException(status_code=404, detail="No extraction found")

	# Load field_values explicitly (async sessions don't support lazy loading).
	fv_stmt = select(ExtractedFieldValue).where(
		ExtractedFieldValue.extraction_id == extraction.id
	)
	fv_result = await db_session.execute(fv_stmt)
	field_values = fv_result.scalars().all()

	return schema.ExtractionResult.from_orm_extraction(extraction, field_values)


@router.patch("/extractions/{extraction_id}/corrections")
async def submit_corrections(
	extraction_id: UUID,
	corrections: schema.CorrectionRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Submit corrections for an extraction."""
	service = FormRecognitionService(db_session)
	await service.update_template_from_corrections(
		extraction_id=extraction_id,
		corrections=corrections.corrections,
	)

	return {"success": True}


@router.get("/signatures/{document_id}")
async def get_document_signatures(
	document_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SignatureListResponse:
	"""Get signatures associated with a document.

	ORM Signature has no extraction_id FK.  We look up signatures via
	captured_from_document_id instead.
	"""
	stmt = select(Signature).where(
		and_(
			Signature.captured_from_document_id == document_id,
			Signature.tenant_id == user.tenant_id,
		)
	)
	result = await db_session.execute(stmt)
	signatures = result.scalars().all()

	return schema.SignatureListResponse(
		signatures=[schema.SignatureInfo.from_orm_signature(s) for s in signatures]
	)


@router.get("/queue")
async def get_extraction_queue(
	user: require_scopes(scopes.NODE_VIEW),
	page: int = 1,
	page_size: int = 20,
	status_filter: str | None = None,
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""List pending/queued form extractions."""
	from sqlalchemy import func
	from .db.orm import ExtractionStatus

	allowed_statuses = {s.value for s in ExtractionStatus}
	if status_filter and status_filter not in allowed_statuses:
		raise HTTPException(status_code=422, detail=f"Invalid status. Allowed: {allowed_statuses}")

	filters = []
	if status_filter:
		filters.append(FormExtraction.status == status_filter)
	else:
		# Default: pending + processing
		filters.append(FormExtraction.status.in_(["pending", "processing"]))

	total = (await db_session.execute(
		select(func.count()).select_from(FormExtraction).where(*filters)
	)).scalar_one()

	rows = (await db_session.execute(
		select(FormExtraction)
		.where(*filters)
		.order_by(FormExtraction.created_at.asc())
		.offset((page - 1) * page_size)
		.limit(page_size)
	)).scalars().all()

	return {
		"items": [
			{
				"id": str(e.id),
				"documentId": str(e.document_id),
				"templateId": str(e.template_id) if e.template_id else None,
				"status": e.status,
				"createdAt": e.created_at.isoformat() if e.created_at else None,
			}
			for e in rows
		],
		"total": total,
		"page": page,
		"pageSize": page_size,
	}
