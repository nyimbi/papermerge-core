# (c) Copyright Datacraft, 2026
"""Document ingestion API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from . import schema
from .db.orm import (
	IngestionSource, IngestionJob, IngestionBatch,
	IngestionTemplate, IngestionValidationRule
)

router = APIRouter(
	prefix="/ingestion",
	tags=["ingestion"],
)

logger = logging.getLogger(__name__)


@router.get("/sources")
async def list_ingestion_sources(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	page: int = 1,
	page_size: int = 20,
) -> schema.SourceListResponse:
	"""List ingestion sources."""
	offset = (page - 1) * page_size

	conditions = [IngestionSource.tenant_id == user.tenant_id]

	count_stmt = select(func.count()).select_from(IngestionSource).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(IngestionSource).where(and_(*conditions)).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	sources = result.scalars().all()

	return schema.SourceListResponse(
		items=[schema.SourceInfo.model_validate(s) for s in sources],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.post("/sources")
async def create_ingestion_source(
	source: schema.SourceCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SourceInfo:
	"""Create an ingestion source."""
	db_source = IngestionSource(
		tenant_id=user.tenant_id,
		name=source.name,
		source_type=source.source_type,
		config=source.config,
		mode=source.mode,
		target_folder_id=source.target_folder_id,
		is_active=False,
	)
	db_session.add(db_source)
	await db_session.commit()
	await db_session.refresh(db_source)

	return schema.SourceInfo.model_validate(db_source)


@router.get("/sources/{source_id}")
async def get_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SourceDetail:
	"""Get ingestion source details."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	return schema.SourceDetail.model_validate(source)


@router.post("/sources/{source_id}/start")
async def start_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Start an ingestion source (e.g., folder watcher)."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	source.is_active = True
	await db_session.commit()

	# Queue the watcher task
	from papermerge.core.tasks import send_task
	send_task(
		"darchiva.ingestion.start_watcher",
		kwargs={"source_id": str(source_id)}
	)

	return {"success": True, "message": "Source started"}


@router.post("/sources/{source_id}/stop")
async def stop_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Stop an ingestion source."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	source.is_active = False
	await db_session.commit()

	return {"success": True, "message": "Source stopped"}


@router.delete("/sources/{source_id}")
async def delete_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_DELETE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Delete an ingestion source."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	await db_session.delete(source)
	await db_session.commit()

	return {"success": True}


@router.get("/jobs")
async def list_ingestion_jobs(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	source_id: UUID | None = None,
	status_filter: str | None = None,
	page: int = 1,
	page_size: int = 50,
) -> schema.JobListResponse:
	"""List ingestion jobs."""
	offset = (page - 1) * page_size

	conditions = [IngestionJob.tenant_id == user.tenant_id]
	if source_id:
		conditions.append(IngestionJob.source_id == source_id)
	if status_filter:
		conditions.append(IngestionJob.status == status_filter)

	count_stmt = select(func.count()).select_from(IngestionJob).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(IngestionJob).where(
		and_(*conditions)
	).order_by(IngestionJob.created_at.desc()).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	jobs = result.scalars().all()

	return schema.JobListResponse(
		items=[schema.JobInfo.model_validate(j) for j in jobs],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get("/jobs/{job_id}")
async def get_ingestion_job(
	job_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.JobDetail:
	"""Get ingestion job details."""
	job = await db_session.get(IngestionJob, job_id)
	if not job:
		raise HTTPException(status_code=404, detail="Job not found")

	return schema.JobDetail.model_validate(job)


@router.post("/email")
async def ingest_from_email(
	request: schema.EmailIngestionRequest,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.IngestionResponse:
	"""Process documents from an email."""
	from papermerge.core.tasks import send_task

	# Queue email processing task
	send_task(
		"darchiva.ingestion.process_email",
		kwargs={
			"tenant_id": str(user.tenant_id),
			"email_data": request.model_dump(),
		}
	)

	return schema.IngestionResponse(
		success=True,
		message="Email processing queued",
	)


# ==================== Batch Endpoints ====================

@router.post("/batch")
async def create_batch(
	batch: schema.BatchCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.BatchInfo:
	"""Create and start a batch ingestion job."""
	db_batch = IngestionBatch(
		tenant_id=user.tenant_id,
		name=batch.name,
		template_id=batch.template_id,
		total_files=len(batch.file_paths) if batch.file_paths else 0,
		status="pending",
		created_by=user.id,
	)
	db_session.add(db_batch)
	await db_session.commit()
	await db_session.refresh(db_batch)

	if batch.file_paths:
		from papermerge.core.tasks import send_task
		send_task(
			"darchiva.ingestion.process_batch",
			kwargs={
				"batch_id": str(db_batch.id),
				"file_paths": batch.file_paths,
				"template_id": str(batch.template_id) if batch.template_id else None,
			}
		)

	return schema.BatchInfo.model_validate(db_batch)


@router.get("/batches")
async def list_batches(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	status_filter: str | None = None,
	page: int = 1,
	page_size: int = 20,
) -> schema.BatchListResponse:
	"""List ingestion batches."""
	offset = (page - 1) * page_size
	conditions = [IngestionBatch.tenant_id == user.tenant_id]
	if status_filter:
		conditions.append(IngestionBatch.status == status_filter)

	count_stmt = select(func.count()).select_from(IngestionBatch).where(and_(*conditions))
	total = await db_session.scalar(count_stmt)

	stmt = select(IngestionBatch).where(
		and_(*conditions)
	).order_by(IngestionBatch.created_at.desc()).offset(offset).limit(page_size)
	result = await db_session.execute(stmt)
	batches = result.scalars().all()

	return schema.BatchListResponse(
		items=[schema.BatchInfo.model_validate(b) for b in batches],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get("/batch/{batch_id}")
async def get_batch(
	batch_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.BatchDetail:
	"""Get batch details with associated jobs."""
	batch = await db_session.get(IngestionBatch, batch_id)
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	jobs_stmt = select(IngestionJob).where(IngestionJob.batch_id == batch_id)
	result = await db_session.execute(jobs_stmt)
	jobs = result.scalars().all()

	batch_dict = {
		"id": batch.id,
		"name": batch.name,
		"template_id": batch.template_id,
		"total_files": batch.total_files,
		"processed_files": batch.processed_files,
		"failed_files": batch.failed_files,
		"status": batch.status,
		"started_at": batch.started_at,
		"completed_at": batch.completed_at,
		"created_at": batch.created_at,
		"jobs": [schema.JobInfo.model_validate(j) for j in jobs],
	}
	return schema.BatchDetail(**batch_dict)


# ==================== Template Endpoints ====================

@router.get("/templates")
async def list_templates(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TemplateListResponse:
	"""List ingestion templates."""
	stmt = select(IngestionTemplate).where(
		IngestionTemplate.tenant_id == user.tenant_id
	).order_by(IngestionTemplate.name)
	result = await db_session.execute(stmt)
	templates = result.scalars().all()

	return schema.TemplateListResponse(
		items=[schema.TemplateInfo.model_validate(t) for t in templates],
		total=len(templates),
	)


@router.post("/templates")
async def create_template(
	template: schema.TemplateCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.TemplateInfo:
	"""Create an ingestion template."""
	db_template = IngestionTemplate(
		tenant_id=user.tenant_id,
		name=template.name,
		description=template.description,
		target_folder_id=template.target_folder_id,
		document_type_id=template.document_type_id,
		apply_ocr=template.apply_ocr,
		auto_classify=template.auto_classify,
		duplicate_check=template.duplicate_check,
		validation_rules=template.validation_rules,
	)
	db_session.add(db_template)
	await db_session.commit()
	await db_session.refresh(db_template)

	return schema.TemplateInfo.model_validate(db_template)


@router.delete("/templates/{template_id}")
async def delete_template(
	template_id: UUID,
	user: require_scopes(scopes.NODE_DELETE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Delete an ingestion template."""
	template = await db_session.get(IngestionTemplate, template_id)
	if not template:
		raise HTTPException(status_code=404, detail="Template not found")

	await db_session.delete(template)
	await db_session.commit()
	return {"success": True}


# ==================== Validation Endpoints ====================

@router.post("/validate")
async def validate_files(
	request: schema.BatchValidationRequest,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> list[schema.FileValidationResult]:
	"""Validate files before ingestion."""
	import os
	import re

	rules = []
	if request.template_id:
		template = await db_session.get(IngestionTemplate, request.template_id)
		if template and template.validation_rules:
			rules = template.validation_rules.get("rules", [])
	else:
		stmt = select(IngestionValidationRule).where(
			and_(
				IngestionValidationRule.tenant_id == user.tenant_id,
				IngestionValidationRule.is_active == True
			)
		)
		result = await db_session.execute(stmt)
		rules = [{"type": r.rule_type, "config": r.config} for r in result.scalars().all()]

	results = []
	for path in request.file_paths:
		errors = []
		warnings = []

		for rule in rules:
			rule_type = rule.get("type") or rule.get("rule_type")
			config = rule.get("config", {})

			if rule_type == "file_size":
				try:
					size_mb = os.path.getsize(path) / (1024 * 1024)
					if config.get("max_mb") and size_mb > config["max_mb"]:
						errors.append(f"File exceeds max size: {size_mb:.1f}MB > {config['max_mb']}MB")
				except OSError:
					warnings.append("Could not check file size")

			elif rule_type == "file_type":
				ext = os.path.splitext(path)[1].lower().lstrip(".")
				allowed = config.get("allowed", [])
				blocked = config.get("blocked", [])
				if blocked and ext in blocked:
					errors.append(f"File type '{ext}' is blocked")
				elif allowed and ext not in allowed:
					errors.append(f"File type '{ext}' not in allowed list: {allowed}")

			elif rule_type == "naming":
				pattern = config.get("pattern")
				if pattern:
					filename = os.path.basename(path)
					if not re.match(pattern, filename):
						errors.append(f"Filename does not match pattern: {pattern}")

		results.append(schema.FileValidationResult(
			valid=len(errors) == 0,
			errors=errors,
			warnings=warnings,
		))

	return results


@router.get("/validation-rules")
async def list_validation_rules(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> list[schema.ValidationRuleInfo]:
	"""List validation rules."""
	stmt = select(IngestionValidationRule).where(
		IngestionValidationRule.tenant_id == user.tenant_id
	)
	result = await db_session.execute(stmt)
	rules = result.scalars().all()
	return [schema.ValidationRuleInfo.model_validate(r) for r in rules]


@router.post("/validation-rules")
async def create_validation_rule(
	rule: schema.ValidationRuleCreate,
	user: require_scopes(scopes.NODE_CREATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.ValidationRuleInfo:
	"""Create a validation rule."""
	db_rule = IngestionValidationRule(
		tenant_id=user.tenant_id,
		name=rule.name,
		rule_type=rule.rule_type,
		config=rule.config,
	)
	db_session.add(db_rule)
	await db_session.commit()
	await db_session.refresh(db_rule)

	return schema.ValidationRuleInfo.model_validate(db_rule)
