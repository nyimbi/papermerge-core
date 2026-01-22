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
from .db.orm import FormTemplate, FormField, FormExtraction, Signature

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
		items=[schema.TemplateInfo.model_validate(t) for t in templates],
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

	return schema.TemplateInfo.model_validate(result)


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

	# Get fields
	stmt = select(FormField).where(
		FormField.template_id == template_id
	).order_by(FormField.order)
	result = await db_session.execute(stmt)
	fields = result.scalars().all()

	return schema.TemplateDetail(
		id=template.id,
		name=template.name,
		category=template.category,
		is_multipage=template.is_multipage,
		page_count=template.page_count,
		is_active=template.is_active,
		fields=[schema.FieldInfo.model_validate(f) for f in fields],
	)


@router.post("/extract")
async def extract_form_data(
	request: schema.ExtractionRequest,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.ExtractionResponse:
	"""Extract form data from a document."""
	from papermerge.core.tasks import send_task

	# Queue extraction task
	send_task(
		"darchiva.form.process",
		kwargs={
			"document_id": str(request.document_id),
			"template_id": str(request.template_id) if request.template_id else None,
			"tenant_id": str(user.tenant_id),
		}
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
	stmt = select(FormExtraction).where(
		FormExtraction.document_id == document_id
	).order_by(FormExtraction.created_at.desc())
	result = await db_session.execute(stmt)
	extraction = result.scalar()

	if not extraction:
		raise HTTPException(status_code=404, detail="No extraction found")

	return schema.ExtractionResult.model_validate(extraction)


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
	"""Get extracted signatures for a document."""
	# Get extraction for document
	stmt = select(FormExtraction).where(
		FormExtraction.document_id == document_id
	)
	result = await db_session.execute(stmt)
	extraction = result.scalar()

	if not extraction:
		return schema.SignatureListResponse(signatures=[])

	# Get signatures
	stmt = select(Signature).where(
		Signature.extraction_id == extraction.id
	)
	result = await db_session.execute(stmt)
	signatures = result.scalars().all()

	return schema.SignatureListResponse(
		signatures=[schema.SignatureInfo.model_validate(s) for s in signatures]
	)
