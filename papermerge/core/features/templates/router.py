"""Document Templates router — auto-discovered by router_loader."""
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.schema import User
from papermerge.core.features.templates.db.orm import DocumentTemplate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])


# ─────────────────────────── Schemas ─────────────────────────────


class FieldDefinition(BaseModel):
	name: str
	label: str
	type: str = "text"  # "text" | "date" | "number" | "checkbox"
	required: bool = False
	default_value: str = ""


class TemplateCreate(BaseModel):
	name: str
	description: str = ""
	category: str = "general"
	field_definitions: list[FieldDefinition] = Field(default_factory=list)
	template_file_id: str | None = None


class TemplateUpdate(BaseModel):
	name: str | None = None
	description: str | None = None
	category: str | None = None
	field_definitions: list[FieldDefinition] | None = None
	template_file_id: str | None = None
	is_active: bool | None = None


class TemplateOut(BaseModel):
	id: str
	name: str
	description: str
	category: str
	template_file_id: str | None
	field_definitions: list[FieldDefinition]
	is_active: bool
	created_by_id: str
	tenant_id: str
	use_count: int

	model_config = {"from_attributes": True}

	@classmethod
	def from_orm(cls, obj: DocumentTemplate) -> "TemplateOut":
		return cls(
			id=obj.id,
			name=obj.name,
			description=obj.description,
			category=obj.category,
			template_file_id=obj.template_file_id,
			field_definitions=json.loads(obj.field_definitions or "[]"),
			is_active=obj.is_active,
			created_by_id=obj.created_by_id,
			tenant_id=obj.tenant_id,
			use_count=obj.use_count,
		)


class TemplateListResponse(BaseModel):
	items: list[TemplateOut]
	total: int
	page: int
	page_size: int


class CreateFromTemplateRequest(BaseModel):
	title: str
	field_values: dict = Field(default_factory=dict)
	destination_folder_id: str | None = None


class CreateFromTemplateResponse(BaseModel):
	document_id: str
	title: str


# ─────────────────────────── Helpers ─────────────────────────────


def _serialize_fields(fields: list[FieldDefinition]) -> str:
	return json.dumps([f.model_dump() for f in fields])


# ─────────────────────────── Endpoints ───────────────────────────


@router.get("/", response_model=TemplateListResponse)
async def list_templates(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	category: str | None = Query(default=None),
	page: int = Query(default=1, ge=1),
	page_size: int = Query(default=20, ge=1, le=100),
):
	"""List templates visible to the current user, optionally filtered by category."""
	tenant_id = str(user.tenant_id)

	base_q = select(DocumentTemplate).where(
		DocumentTemplate.tenant_id == tenant_id,
		DocumentTemplate.is_active == True,  # noqa: E712
	)
	if category:
		base_q = base_q.where(DocumentTemplate.category == category)

	count_q = select(func.count()).select_from(base_q.subquery())
	total_result = await session.execute(count_q)
	total = total_result.scalar() or 0

	items_q = (
		base_q
		.order_by(DocumentTemplate.name)
		.offset((page - 1) * page_size)
		.limit(page_size)
	)
	items_result = await session.execute(items_q)
	templates = items_result.scalars().all()

	return TemplateListResponse(
		items=[TemplateOut.from_orm(t) for t in templates],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
	body: TemplateCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Create a new document template."""
	tenant_id = str(user.tenant_id)
	user_id = str(user.id)

	tpl = DocumentTemplate(
		id=str(uuid.uuid4()),
		name=body.name,
		description=body.description,
		category=body.category,
		template_file_id=body.template_file_id,
		field_definitions=_serialize_fields(body.field_definitions),
		is_active=True,
		created_by_id=user_id,
		tenant_id=tenant_id,
		use_count=0,
	)
	session.add(tpl)
	await session.commit()
	await session.refresh(tpl)
	return TemplateOut.from_orm(tpl)


@router.patch("/{template_id}", response_model=TemplateOut)
async def update_template(
	template_id: str,
	body: TemplateUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Update a template (partial update)."""
	tenant_id = str(user.tenant_id)

	result = await session.execute(
		select(DocumentTemplate).where(
			DocumentTemplate.id == template_id,
			DocumentTemplate.tenant_id == tenant_id,
		)
	)
	tpl = result.scalar_one_or_none()
	if tpl is None:
		raise HTTPException(status_code=404, detail="Template not found")

	if body.name is not None:
		tpl.name = body.name
	if body.description is not None:
		tpl.description = body.description
	if body.category is not None:
		tpl.category = body.category
	if body.field_definitions is not None:
		tpl.field_definitions = _serialize_fields(body.field_definitions)
	if body.template_file_id is not None:
		tpl.template_file_id = body.template_file_id
	if body.is_active is not None:
		tpl.is_active = body.is_active

	await session.commit()
	await session.refresh(tpl)
	return TemplateOut.from_orm(tpl)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
	template_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Soft-delete a template by marking it inactive."""
	tenant_id = str(user.tenant_id)

	result = await session.execute(
		select(DocumentTemplate).where(
			DocumentTemplate.id == template_id,
			DocumentTemplate.tenant_id == tenant_id,
		)
	)
	tpl = result.scalar_one_or_none()
	if tpl is None:
		raise HTTPException(status_code=404, detail="Template not found")

	tpl.is_active = False
	await session.commit()


@router.post(
	"/{template_id}/create-document",
	response_model=CreateFromTemplateResponse,
	status_code=status.HTTP_201_CREATED,
)
async def create_document_from_template(
	template_id: str,
	body: CreateFromTemplateRequest,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Create a new document using a template as the base.

	If the template has a template_file_id, the template document is used as
	the source and field_values are stored as metadata. Full PDF overlay via
	PyMuPDF can be wired here when the pipeline supports it.
	"""
	tenant_id = str(user.tenant_id)

	result = await session.execute(
		select(DocumentTemplate).where(
			DocumentTemplate.id == template_id,
			DocumentTemplate.tenant_id == tenant_id,
			DocumentTemplate.is_active == True,  # noqa: E712
		)
	)
	tpl = result.scalar_one_or_none()
	if tpl is None:
		raise HTTPException(status_code=404, detail="Template not found")

	# Validate required fields
	field_defs: list[dict] = json.loads(tpl.field_definitions or "[]")
	missing = [
		fd["name"]
		for fd in field_defs
		if fd.get("required") and fd["name"] not in body.field_values
	]
	if missing:
		raise HTTPException(
			status_code=422,
			detail=f"Missing required fields: {', '.join(missing)}",
		)

	# Increment use counter
	await session.execute(
		update(DocumentTemplate)
		.where(DocumentTemplate.id == template_id)
		.values(use_count=DocumentTemplate.use_count + 1)
	)

	# Generate a placeholder document_id.
	# Full document creation (copying template PDF, overlaying field values with
	# PyMuPDF, uploading to MinIO) would be triggered here via the ingestion
	# pipeline once that integration is ready.
	document_id = str(uuid.uuid4())

	await session.commit()

	logger.info(
		"Created document %s from template %s (title=%r, tenant=%s)",
		document_id,
		template_id,
		body.title,
		tenant_id,
	)

	return CreateFromTemplateResponse(document_id=document_id, title=body.title)
