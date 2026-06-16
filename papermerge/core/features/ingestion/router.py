# (c) Copyright Datacraft, 2026
"""Document ingestion API endpoints."""
import hashlib
import hmac
import logging
import uuid
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Depends, Header, Request, UploadFile, status
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


@router.get("/sources/dashboard")
async def get_sources_dashboard(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SourceDashboardResponse:
	"""Aggregate health + activity across all ingestion source types.

	Covers:
	  - ingestion_sources (watched_folder, email, api, scanner)
	  - email_accounts (IMAP / OAuth)
	  - scan_agents fleet
	"""
	from datetime import datetime, timezone, timedelta
	from sqlalchemy import text

	now = datetime.now(timezone.utc)
	cutoff_24h = now - timedelta(hours=24)
	cutoff_7d = now - timedelta(days=7)
	tenant_id = str(user.tenant_id)

	items: list[schema.SourceDashboardItem] = []

	# ── 1. ingestion_sources rows ────────────────────────────────────────────
	src_stmt = select(IngestionSource).where(
		IngestionSource.tenant_id == user.tenant_id
	)
	result = await db_session.execute(src_stmt)
	ing_sources = result.scalars().all()

	for src in ing_sources:
		# Count completed jobs in 24h / 7d
		def _job_count(cutoff: datetime) -> "select":
			return (
				select(func.count())
				.select_from(IngestionJob)
				.where(
					IngestionJob.source_id == src.id,
					IngestionJob.status == "completed",
					IngestionJob.created_at >= cutoff,
				)
			)

		docs_24h = (await db_session.scalar(_job_count(cutoff_24h))) or 0
		docs_7d = (await db_session.scalar(_job_count(cutoff_7d))) or 0

		# Count failed jobs (all-time acts as error_count indicator)
		err_stmt = (
			select(func.count())
			.select_from(IngestionJob)
			.where(
				IngestionJob.source_id == src.id,
				IngestionJob.status == "failed",
			)
		)
		error_count = (await db_session.scalar(err_stmt)) or 0

		# Last error message
		last_err_stmt = (
			select(IngestionJob.error_message)
			.where(
				IngestionJob.source_id == src.id,
				IngestionJob.status == "failed",
				IngestionJob.error_message.isnot(None),
			)
			.order_by(IngestionJob.created_at.desc())
			.limit(1)
		)
		last_error = await db_session.scalar(last_err_stmt)

		if not src.is_active:
			status = "inactive"
		elif error_count > 0:
			status = "error"
		else:
			status = "active"

		items.append(schema.SourceDashboardItem(
			id=str(src.id),
			type=src.source_type,
			name=src.name,
			status=status,
			last_activity_at=src.last_checked_at,
			docs_ingested_24h=docs_24h,
			docs_ingested_7d=docs_7d,
			error_count=error_count,
			last_error=last_error,
		))

	# ── 2. email_accounts ────────────────────────────────────────────────────
	try:
		from papermerge.core.features.emails.models import EmailAccountModel, EmailImportModel
		ea_stmt = select(EmailAccountModel).where(
			EmailAccountModel.owner_id.in_(
				select(text("id")).select_from(text("users")).where(
					text("tenant_id = :tid")
				).params(tid=tenant_id)
			)
		)
		ea_result = await db_session.execute(ea_stmt)
		email_accounts = ea_result.scalars().all()

		for acct in email_accounts:
			# docs ingested via this account
			def _email_count(cutoff: datetime) -> "select":
				return (
					select(func.count())
					.select_from(EmailImportModel)
					.where(
						EmailImportModel.source_account_id == acct.id,
						EmailImportModel.import_status == "completed",
						EmailImportModel.created_at >= cutoff,
					)
				)

			docs_24h = (await db_session.scalar(_email_count(cutoff_24h))) or 0
			docs_7d = (await db_session.scalar(_email_count(cutoff_7d))) or 0

			if not acct.is_active:
				status = "inactive"
			elif acct.connection_status == "error":
				status = "error"
			elif acct.connection_status == "connected":
				status = "active"
			else:
				status = "inactive"

			items.append(schema.SourceDashboardItem(
				id=str(acct.id),
				type="email_account",
				name=acct.name,
				status=status,
				last_activity_at=acct.last_sync_at,
				docs_ingested_24h=docs_24h,
				docs_ingested_7d=docs_7d,
				error_count=1 if acct.connection_error else 0,
				last_error=acct.connection_error,
			))
	except Exception as exc:
		logger.debug("email_accounts dashboard aggregation skipped: %s", exc)

	# ── 3. scan_agents ───────────────────────────────────────────────────────
	try:
		from papermerge.core.features.agents.models import AgentModel
		from datetime import timezone as _tz
		agent_stmt = select(AgentModel).where(AgentModel.tenant_id == tenant_id)
		agent_result = await db_session.execute(agent_stmt)
		agents = agent_result.scalars().all()

		online_threshold = now - timedelta(minutes=5)

		for agent in agents:
			last_seen = agent.last_seen
			if last_seen and last_seen.tzinfo is None:
				last_seen = last_seen.replace(tzinfo=_tz.utc)

			if last_seen and last_seen >= online_threshold:
				status = "active"
			elif last_seen:
				status = "inactive"
			else:
				status = "inactive"

			items.append(schema.SourceDashboardItem(
				id=str(agent.id),
				type="scan_agent",
				name=agent.name or agent.hostname,
				status=status,
				last_activity_at=last_seen,
				docs_ingested_24h=0,
				docs_ingested_7d=0,
				error_count=0,
				last_error=None,
			))
	except Exception as exc:
		logger.debug("scan_agents dashboard aggregation skipped: %s", exc)

	return schema.SourceDashboardResponse(sources=items)


@router.post("/sources/{source_id}/retry")
async def retry_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Re-trigger a failed ingestion source sync."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	# Reset any failed jobs for this source to pending so they are retried
	failed_jobs_stmt = (
		select(IngestionJob)
		.where(
			IngestionJob.source_id == source_id,
			IngestionJob.status == "failed",
		)
		.limit(50)
	)
	result = await db_session.execute(failed_jobs_stmt)
	failed_jobs = result.scalars().all()
	for job in failed_jobs:
		job.status = "pending"
		job.retry_count = (job.retry_count or 0) + 1

	# Activate the source if it was inactive
	if not source.is_active:
		source.is_active = True

	await db_session.commit()

	# Queue the watcher/processor task
	from papermerge.core.tasks import send_task
	send_task("darchiva.ingestion.start_watcher", kwargs={"source_id": str(source_id)})

	return {
		"success": True,
		"message": f"Source {source.name} re-triggered, {len(failed_jobs)} failed job(s) reset to pending",
	}


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
		default_document_type_id=source.default_document_type_id,
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


@router.patch("/sources/{source_id}")
async def update_ingestion_source(
	source_id: UUID,
	updates: dict,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> schema.SourceInfo:
	"""Update ingestion source name/config."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")
	if "name" in updates:
		source.name = updates["name"]
	if "config" in updates:
		source.config = {**source.config, **updates["config"]}
	if "mode" in updates:
		source.mode = updates["mode"]
	await db_session.commit()
	await db_session.refresh(source)
	return schema.SourceInfo.model_validate(source)


@router.patch("/sources/{source_id}/toggle")
async def toggle_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Toggle an ingestion source active/inactive."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")
	source.is_active = not source.is_active
	await db_session.commit()
	return {"is_active": source.is_active}


@router.post("/sources/{source_id}/trigger")
async def trigger_ingestion_source(
	source_id: UUID,
	user: require_scopes(scopes.NODE_UPDATE),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Trigger an immediate run of an ingestion source."""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")
	from papermerge.core.tasks import send_task
	send_task("darchiva.ingestion.start_watcher", kwargs={"source_id": str(source_id)})
	return {"success": True, "message": "Source triggered"}


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


@router.get("/stats")
async def get_ingestion_stats(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.IngestionStats:
	"""Get ingestion statistics for the current tenant."""
	from datetime import datetime
	today = datetime.utcnow().date()

	# Total sources
	total_stmt = select(func.count()).select_from(IngestionSource).where(
		IngestionSource.tenant_id == user.tenant_id
	)
	total = await db_session.scalar(total_stmt) or 0

	# Active sources
	active_stmt = select(func.count()).select_from(IngestionSource).where(
		IngestionSource.tenant_id == user.tenant_id,
		IngestionSource.is_active == True
	)
	active = await db_session.scalar(active_stmt) or 0

	# Jobs today
	today_stmt = (
		select(func.count())
		.select_from(IngestionJob)
		.join(IngestionSource, IngestionJob.source_id == IngestionSource.id)
		.where(
			IngestionSource.tenant_id == user.tenant_id,
			func.date(IngestionJob.created_at) == today
		)
	)
	jobs_today = await db_session.scalar(today_stmt) or 0

	# Failed jobs today
	failed_stmt = (
		select(func.count())
		.select_from(IngestionJob)
		.join(IngestionSource, IngestionJob.source_id == IngestionSource.id)
		.where(
			IngestionSource.tenant_id == user.tenant_id,
			func.date(IngestionJob.created_at) == today,
			IngestionJob.status == "failed"
		)
	)
	failed_today = await db_session.scalar(failed_stmt) or 0

	success_rate = 100.0 if jobs_today == 0 else round((jobs_today - failed_today) / jobs_today * 100, 1)

	return schema.IngestionStats(
		active=active,
		total=total,
		jobs_today=jobs_today,
		failed=failed_today,
		success_rate=success_rate,
	)


@router.get("/jobs")
async def list_ingestion_jobs(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	source_id: UUID | None = None,
	status_filter: str | None = None,
	page: int = 1,
	page_size: int = 50,
	limit: int | None = None,  # Alias for page_size
) -> schema.JobListResponse:
	"""List ingestion jobs."""
	effective_page_size = limit or page_size
	offset = (page - 1) * effective_page_size

	# Join with IngestionSource to filter by tenant_id
	conditions = [IngestionSource.tenant_id == user.tenant_id]
	if source_id:
		conditions.append(IngestionJob.source_id == source_id)
	if status_filter:
		conditions.append(IngestionJob.status == status_filter)

	count_stmt = (
		select(func.count())
		.select_from(IngestionJob)
		.join(IngestionSource, IngestionJob.source_id == IngestionSource.id)
		.where(and_(*conditions))
	)
	total = await db_session.scalar(count_stmt) or 0

	stmt = (
		select(IngestionJob)
		.join(IngestionSource, IngestionJob.source_id == IngestionSource.id)
		.where(and_(*conditions))
		.order_by(IngestionJob.created_at.desc())
		.offset(offset)
		.limit(effective_page_size)
	)
	result = await db_session.execute(stmt)
	jobs = result.scalars().all()

	return schema.JobListResponse(
		items=[schema.JobInfo.model_validate(j) for j in jobs],
		total=total,
		page=page,
		page_size=effective_page_size,
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


@router.post("/webhook/{source_id}", status_code=status.HTTP_202_ACCEPTED)
async def webhook_ingest(
	source_id: UUID,
	request: Request,
	db_session: AsyncSession = Depends(get_db),
	x_hub_signature_256: str | None = Header(default=None),
) -> dict:
	"""Receive a document via webhook from an external source.

	Accepts either multipart/form-data with a 'file' field or a raw body.
	Verifies the HMAC-SHA256 signature in X-Hub-Signature-256 against the
	webhook_secret stored in IngestionSource.config['webhook_secret'].
	Returns 202 Accepted with {job_id, status} on success.
	"""
	source = await db_session.get(IngestionSource, source_id)
	if not source:
		raise HTTPException(status_code=404, detail="Source not found")

	webhook_secret: str | None = source.config.get("webhook_secret") if source.config else None
	if not webhook_secret:
		raise HTTPException(
			status_code=401,
			detail="Webhook secret not configured for this source",
		)

	# Read the raw body for signature verification regardless of content-type
	body = await request.body()

	if not x_hub_signature_256:
		raise HTTPException(
			status_code=401,
			detail="Missing X-Hub-Signature-256 header",
		)

	expected_sig = "sha256=" + hmac.new(
		webhook_secret.encode("utf-8"), body, hashlib.sha256
	).hexdigest()
	if not hmac.compare_digest(expected_sig, x_hub_signature_256):
		raise HTTPException(status_code=401, detail="Invalid webhook signature")

	# Determine source_path from file upload or raw body Content-Type
	content_type = request.headers.get("content-type", "")
	source_path: str | None = None

	if content_type.startswith("multipart/form-data"):
		form = await request.form()
		file_field = form.get("file")
		if file_field is not None and hasattr(file_field, "filename"):
			source_path = file_field.filename or "webhook-upload"
	else:
		source_path = f"webhook:{content_type or 'application/octet-stream'}"

	# Dedup check — block exact duplicates, flag near-duplicates
	from .dedup import check_duplicate, record_fingerprint, DedupVerdict
	dedup = await check_duplicate(db_session, body, str(source.tenant_id))
	dedup_meta: dict = {"dedup_verdict": dedup.verdict, "sha256": dedup.sha256}
	if dedup.verdict == DedupVerdict.EXACT_DUPLICATE:
		return {
			"job_id": None,
			"status": "duplicate",
			"dedup": {
				"verdict": dedup.verdict,
				"existing_document_id": dedup.existing_document_id,
			},
		}
	if dedup.verdict == DedupVerdict.NEAR_DUPLICATE:
		dedup_meta["existing_document_id"] = dedup.existing_document_id
		dedup_meta["hamming_distance"] = dedup.hamming_distance

	job_id = uuid.uuid4()
	job = IngestionJob(
		id=job_id,
		source_id=source_id,
		source_path=source_path,
		source_metadata={
			"content_type": content_type,
			"content_length": len(body),
			"source_type": "webhook",
			**dedup_meta,
		},
		status="pending",
	)
	db_session.add(job)
	await db_session.commit()

	logger.info("Webhook ingestion job %s created for source %s", job_id, source_id)
	return {
		"job_id": str(job_id),
		"status": "pending",
		"dedup": {"verdict": dedup.verdict} if dedup.verdict != DedupVerdict.UNIQUE else None,
	}


@router.post("/detect-barcodes")
async def detect_barcodes_in_upload(
	file: UploadFile = File(...),
	db_session: AsyncSession = Depends(get_db),
) -> list[dict]:
	"""Detect barcodes and QR codes in an uploaded image.

	Returns a list of detected codes with value, type, and confidence.
	Used for scan-time dedup (re-scan prevention) and document identity assignment.
	"""
	from .barcode import detect_barcodes, _CV2_AVAILABLE
	if not _CV2_AVAILABLE:
		raise HTTPException(status_code=503, detail="opencv-python not installed")
	data = await file.read()
	results = detect_barcodes(data)
	return [
		{"value": r.value, "type": r.barcode_type, "confidence": r.confidence, "bbox": r.bbox}
		for r in results
	]


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
