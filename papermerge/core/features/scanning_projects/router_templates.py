# (c) Copyright Datacraft, 2026
"""CRUD endpoints for scanning batch templates.

Auto-discovered by router_loader as router_templates.py → registered as
GET/POST/PATCH/DELETE /scanning-projects/batch-templates/...
"""
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.features.users.schema import User
from papermerge.core.utils.uuid_compat import uuid7str

from .models_templates import BatchTemplateModel
from .models import ScanningBatchModel
from .views_templates import BatchTemplate, BatchTemplateCreate, BatchTemplateUpdate

router = APIRouter(
	prefix="/scanning-projects",
	tags=["scanning-project-templates"],
)

_log = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _row_to_schema(row: BatchTemplateModel) -> BatchTemplate:
	return BatchTemplate.model_validate(row)


async def _get_or_404(db: AsyncSession, template_id: str) -> BatchTemplateModel:
	result = await db.execute(
		select(BatchTemplateModel).where(BatchTemplateModel.id == template_id)
	)
	tpl = result.scalar_one_or_none()
	if not tpl:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
	return tpl


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("/batch-templates", response_model=list[BatchTemplate])
async def list_batch_templates(
	user: Annotated[User, Depends(require_scopes(scopes.NODE_VIEW))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> list[BatchTemplate]:
	"""List all batch templates for the current tenant."""
	tenant_id = str(user.tenant_id) if hasattr(user, "tenant_id") else str(user.id)
	result = await db.execute(
		select(BatchTemplateModel)
		.where(BatchTemplateModel.tenant_id == tenant_id)
		.order_by(BatchTemplateModel.usage_count.desc(), BatchTemplateModel.name)
	)
	rows = result.scalars().all()
	return [_row_to_schema(r) for r in rows]


@router.post(
	"/batch-templates",
	response_model=BatchTemplate,
	status_code=status.HTTP_201_CREATED,
)
async def create_batch_template(
	body: BatchTemplateCreate,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_CREATE))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> BatchTemplate:
	"""Create a new batch template."""
	tenant_id = str(user.tenant_id) if hasattr(user, "tenant_id") else str(user.id)

	# Enforce uniqueness at app layer for clearer error messages
	existing = await db.execute(
		select(BatchTemplateModel).where(
			BatchTemplateModel.tenant_id == tenant_id,
			BatchTemplateModel.name == body.name,
		)
	)
	if existing.scalar_one_or_none():
		raise HTTPException(
			status_code=status.HTTP_409_CONFLICT,
			detail=f"A template named '{body.name}' already exists for this tenant",
		)

	tpl = BatchTemplateModel(
		id=uuid7str(),
		tenant_id=tenant_id,
		created_by_id=str(user.id),
		**body.model_dump(),
	)
	db.add(tpl)
	await db.commit()
	await db.refresh(tpl)
	_log.info("BatchTemplate %s created by user %s", tpl.id, user.id)
	return _row_to_schema(tpl)


@router.patch("/batch-templates/{template_id}", response_model=BatchTemplate)
async def update_batch_template(
	template_id: str,
	body: BatchTemplateUpdate,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_UPDATE))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> BatchTemplate:
	"""Update a batch template's fields."""
	tpl = await _get_or_404(db, template_id)

	updates = body.model_dump(exclude_unset=True)
	for key, val in updates.items():
		setattr(tpl, key, val)
	tpl.updated_at = datetime.utcnow()

	await db.commit()
	await db.refresh(tpl)
	return _row_to_schema(tpl)


@router.delete("/batch-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_batch_template(
	template_id: str,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_DELETE))],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a batch template."""
	tpl = await _get_or_404(db, template_id)
	await db.delete(tpl)
	await db.commit()
	_log.info("BatchTemplate %s deleted by user %s", template_id, user.id)


@router.post(
	"/batch-templates/{template_id}/apply",
	response_model=dict,
)
async def apply_template_to_batch(
	template_id: str,
	user: Annotated[User, Depends(require_scopes(scopes.NODE_UPDATE))],
	db: Annotated[AsyncSession, Depends(get_db)],
	batch_id: str = Query(..., description="Batch to apply the template to"),
) -> dict:
	"""Apply a template's scan settings to an existing batch.

	Overwrites: notes (if notes_template set), and stores template metadata on batch.
	Also increments template.usage_count.
	"""
	tpl = await _get_or_404(db, template_id)

	batch_result = await db.execute(
		select(ScanningBatchModel).where(ScanningBatchModel.id == batch_id)
	)
	batch = batch_result.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")

	# Apply notes_template → batch.notes if set
	if tpl.notes_template:
		batch.notes = tpl.notes_template

	tpl.usage_count = (tpl.usage_count or 0) + 1
	tpl.updated_at = datetime.utcnow()

	await db.commit()

	_log.info(
		"Template %s applied to batch %s by user %s (usage_count=%d)",
		template_id, batch_id, user.id, tpl.usage_count,
	)

	return {
		"template_id": template_id,
		"batch_id": batch_id,
		"applied": {
			"dpi": tpl.dpi,
			"color_mode": tpl.color_mode,
			"paper_size": tpl.paper_size,
			"quality_threshold": tpl.quality_threshold,
			"barcode_enabled": tpl.barcode_enabled,
			"auto_deskew": tpl.auto_deskew,
			"auto_enhance": tpl.auto_enhance,
			"expected_pages_per_document": tpl.expected_pages_per_document,
			"notes_template": tpl.notes_template,
		},
		"usage_count": tpl.usage_count,
	}
