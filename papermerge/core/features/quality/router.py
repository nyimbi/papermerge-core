# (c) Copyright Datacraft, 2026
"""Quality management API endpoints."""
import base64
import logging
from uuid import UUID
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from . import schema
from .db.orm import QualityRule, QualityAssessment, QualityIssueRecord, IssueStatus

router = APIRouter(
	prefix="/quality",
	tags=["quality"],
)

logger = logging.getLogger(__name__)


# Quality Rules endpoints
@router.get("/rules")
async def list_quality_rules(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	active_only: bool = False,
	metric: str | None = None,
) -> schema.QualityRuleListResponse:
	"""List quality rules for the tenant."""
	conditions = [QualityRule.tenant_id == user.tenant_id]
	if active_only:
		conditions.append(QualityRule.is_active == True)
	if metric:
		conditions.append(QualityRule.metric == metric)

	count_stmt = select(func.count()).select_from(QualityRule).where(*conditions)
	total = await db_session.scalar(count_stmt) or 0

	stmt = (
		select(QualityRule)
		.where(*conditions)
		.order_by(QualityRule.priority, QualityRule.name)
	)
	result = await db_session.execute(stmt)
	rules = result.scalars().all()

	return schema.QualityRuleListResponse(
		items=[schema.QualityRuleInfo.model_validate(r) for r in rules],
		total=total,
	)


@router.post("/rules")
async def create_quality_rule(
	rule_data: schema.QualityRuleCreate,
	user: require_scopes(scopes.SETTINGS_EDIT),
	db_session: AsyncSession = Depends(get_db),
) -> schema.QualityRuleInfo:
	"""Create a new quality rule."""
	rule = QualityRule(
		tenant_id=user.tenant_id,
		name=rule_data.name,
		description=rule_data.description,
		metric=rule_data.metric,
		operator=rule_data.operator,
		threshold=rule_data.threshold,
		threshold_upper=rule_data.threshold_upper,
		severity=rule_data.severity,
		action=rule_data.action,
		message_template=rule_data.message_template,
		priority=rule_data.priority,
		document_type_id=rule_data.document_type_id,
		applies_to_all=rule_data.applies_to_all,
	)
	db_session.add(rule)
	await db_session.commit()
	await db_session.refresh(rule)

	return schema.QualityRuleInfo.model_validate(rule)


@router.get("/rules/{rule_id}")
async def get_quality_rule(
	rule_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> schema.QualityRuleInfo:
	"""Get a specific quality rule."""
	stmt = select(QualityRule).where(
		and_(
			QualityRule.id == rule_id,
			QualityRule.tenant_id == user.tenant_id,
		)
	)
	result = await db_session.execute(stmt)
	rule = result.scalar()

	if not rule:
		raise HTTPException(status_code=404, detail="Rule not found")

	return schema.QualityRuleInfo.model_validate(rule)


@router.patch("/rules/{rule_id}")
async def update_quality_rule(
	rule_id: UUID,
	updates: schema.QualityRuleUpdate,
	user: require_scopes(scopes.SETTINGS_EDIT),
	db_session: AsyncSession = Depends(get_db),
) -> schema.QualityRuleInfo:
	"""Update a quality rule."""
	stmt = select(QualityRule).where(
		and_(
			QualityRule.id == rule_id,
			QualityRule.tenant_id == user.tenant_id,
		)
	)
	result = await db_session.execute(stmt)
	rule = result.scalar()

	if not rule:
		raise HTTPException(status_code=404, detail="Rule not found")

	update_data = updates.model_dump(exclude_unset=True)
	for field, value in update_data.items():
		setattr(rule, field, value)

	await db_session.commit()
	await db_session.refresh(rule)

	return schema.QualityRuleInfo.model_validate(rule)


@router.delete("/rules/{rule_id}")
async def delete_quality_rule(
	rule_id: UUID,
	user: require_scopes(scopes.SETTINGS_EDIT),
	db_session: AsyncSession = Depends(get_db),
) -> dict:
	"""Delete a quality rule."""
	stmt = select(QualityRule).where(
		and_(
			QualityRule.id == rule_id,
			QualityRule.tenant_id == user.tenant_id,
		)
	)
	result = await db_session.execute(stmt)
	rule = result.scalar()

	if not rule:
		raise HTTPException(status_code=404, detail="Rule not found")

	await db_session.delete(rule)
	await db_session.commit()

	return {"success": True}


# Quality Assessments endpoints
@router.get("/assessments")
async def list_assessments(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	document_id: UUID | None = None,
	passed: bool | None = None,
	min_score: float | None = None,
	max_score: float | None = None,
	page: int = 1,
	page_size: int = 50,
) -> schema.QualityAssessmentListResponse:
	"""List quality assessments."""
	offset = (page - 1) * page_size

	# Build conditions - need to join with documents to filter by tenant
	conditions = []
	if document_id:
		conditions.append(QualityAssessment.document_id == document_id)
	if passed is not None:
		conditions.append(QualityAssessment.passed == passed)
	if min_score is not None:
		conditions.append(QualityAssessment.quality_score >= min_score)
	if max_score is not None:
		conditions.append(QualityAssessment.quality_score <= max_score)

	count_stmt = select(func.count()).select_from(QualityAssessment)
	if conditions:
		count_stmt = count_stmt.where(*conditions)
	total = await db_session.scalar(count_stmt) or 0

	stmt = select(QualityAssessment)
	if conditions:
		stmt = stmt.where(*conditions)
	stmt = stmt.order_by(QualityAssessment.assessed_at.desc()).offset(offset).limit(page_size)

	result = await db_session.execute(stmt)
	assessments = result.scalars().all()

	items = []
	for a in assessments:
		metrics = schema.QualityMetricsInfo(
			resolution_dpi=a.resolution_dpi,
			skew_angle=a.skew_angle,
			brightness=a.brightness,
			contrast=a.contrast,
			sharpness=a.sharpness,
			noise_level=a.noise_level,
			blur_score=a.blur_score,
			ocr_confidence=a.ocr_confidence,
			is_blank=a.is_blank,
			orientation=a.orientation,
			width_px=a.width_px,
			height_px=a.height_px,
			file_size_bytes=a.file_size_bytes,
		)

		# Get issues
		issues_stmt = select(QualityIssueRecord).where(
			QualityIssueRecord.assessment_id == a.id
		)
		issues_result = await db_session.execute(issues_stmt)
		issues = issues_result.scalars().all()

		items.append(schema.QualityAssessmentInfo(
			id=a.id,
			document_id=a.document_id,
			page_number=a.page_number,
			quality_score=a.quality_score,
			passed=a.passed,
			grade=_get_grade(a.quality_score),
			metrics=metrics,
			issues=[
				schema.QualityIssueInfo(
					metric=i.metric,
					actual_value=i.actual_value,
					expected_value=i.expected_value,
					severity=i.severity,
					message=i.message,
					page_number=i.page_number,
				)
				for i in issues
			],
			issue_count=a.issue_count,
			critical_issues=a.critical_issues,
			assessed_at=a.assessed_at,
			assessed_by=a.assessed_by,
		))

	return schema.QualityAssessmentListResponse(
		items=items,
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get("/assessments/{document_id}")
async def get_document_assessments(
	document_id: UUID,
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
) -> list[schema.QualityAssessmentInfo]:
	"""Get all assessments for a document."""
	stmt = (
		select(QualityAssessment)
		.where(QualityAssessment.document_id == document_id)
		.order_by(QualityAssessment.page_number.nullsfirst())
	)
	result = await db_session.execute(stmt)
	assessments = result.scalars().all()

	items = []
	for a in assessments:
		metrics = schema.QualityMetricsInfo(
			resolution_dpi=a.resolution_dpi,
			skew_angle=a.skew_angle,
			brightness=a.brightness,
			contrast=a.contrast,
			sharpness=a.sharpness,
			noise_level=a.noise_level,
			blur_score=a.blur_score,
			ocr_confidence=a.ocr_confidence,
			is_blank=a.is_blank,
			orientation=a.orientation,
			width_px=a.width_px,
			height_px=a.height_px,
			file_size_bytes=a.file_size_bytes,
		)

		# Get issues
		issues_stmt = select(QualityIssueRecord).where(
			QualityIssueRecord.assessment_id == a.id
		)
		issues_result = await db_session.execute(issues_stmt)
		issues = issues_result.scalars().all()

		items.append(schema.QualityAssessmentInfo(
			id=a.id,
			document_id=a.document_id,
			page_number=a.page_number,
			quality_score=a.quality_score,
			passed=a.passed,
			grade=_get_grade(a.quality_score),
			metrics=metrics,
			issues=[
				schema.QualityIssueInfo(
					metric=i.metric,
					actual_value=i.actual_value,
					expected_value=i.expected_value,
					severity=i.severity,
					message=i.message,
					page_number=i.page_number,
				)
				for i in issues
			],
			issue_count=a.issue_count,
			critical_issues=a.critical_issues,
			assessed_at=a.assessed_at,
			assessed_by=a.assessed_by,
		))

	return items


# Quality Issues endpoints
@router.get("/issues")
async def list_issues(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	status: str | None = None,
	severity: str | None = None,
	document_id: UUID | None = None,
	page: int = 1,
	page_size: int = 50,
) -> dict:
	"""List quality issues."""
	offset = (page - 1) * page_size

	conditions = []
	if status:
		conditions.append(QualityIssueRecord.status == status)
	if severity:
		conditions.append(QualityIssueRecord.severity == severity)
	if document_id:
		conditions.append(QualityIssueRecord.document_id == document_id)

	count_stmt = select(func.count()).select_from(QualityIssueRecord)
	if conditions:
		count_stmt = count_stmt.where(*conditions)
	total = await db_session.scalar(count_stmt) or 0

	stmt = select(QualityIssueRecord)
	if conditions:
		stmt = stmt.where(*conditions)
	stmt = stmt.order_by(QualityIssueRecord.created_at.desc()).offset(offset).limit(page_size)

	result = await db_session.execute(stmt)
	issues = result.scalars().all()

	return {
		"items": [schema.QualityIssueDetail.model_validate(i) for i in issues],
		"total": total,
		"page": page,
		"page_size": page_size,
	}


@router.patch("/issues/{issue_id}")
async def update_issue(
	issue_id: UUID,
	update_data: schema.QualityIssueUpdateRequest,
	user: require_scopes(scopes.NODE_EDIT),
	db_session: AsyncSession = Depends(get_db),
) -> schema.QualityIssueDetail:
	"""Update a quality issue status."""
	issue = await db_session.get(QualityIssueRecord, issue_id)
	if not issue:
		raise HTTPException(status_code=404, detail="Issue not found")

	issue.status = update_data.status
	if update_data.resolution_notes:
		issue.resolution_notes = update_data.resolution_notes

	if update_data.status in [IssueStatus.RESOLVED.value, IssueStatus.IGNORED.value]:
		issue.resolved_at = datetime.utcnow()
		issue.resolved_by = user.id

	await db_session.commit()
	await db_session.refresh(issue)

	return schema.QualityIssueDetail.model_validate(issue)


# Statistics endpoint
@router.get("/stats")
async def get_quality_stats(
	user: require_scopes(scopes.NODE_VIEW),
	db_session: AsyncSession = Depends(get_db),
	days: int = 7,
) -> schema.QualityStatsInfo:
	"""Get quality statistics for the tenant."""
	# Total assessments
	total_stmt = select(func.count()).select_from(QualityAssessment)
	total = await db_session.scalar(total_stmt) or 0

	# Passed/failed counts
	passed_stmt = select(func.count()).select_from(QualityAssessment).where(
		QualityAssessment.passed == True
	)
	passed = await db_session.scalar(passed_stmt) or 0
	failed = total - passed

	# Average score
	avg_stmt = select(func.avg(QualityAssessment.quality_score))
	avg_score = await db_session.scalar(avg_stmt) or 0.0

	# Issues by severity
	severity_stmt = select(
		QualityIssueRecord.severity,
		func.count().label("count")
	).group_by(QualityIssueRecord.severity)
	severity_result = await db_session.execute(severity_stmt)
	issues_by_severity = {row[0]: row[1] for row in severity_result.fetchall()}

	# Issues by metric
	metric_stmt = select(
		QualityIssueRecord.metric,
		func.count().label("count")
	).group_by(QualityIssueRecord.metric)
	metric_result = await db_session.execute(metric_stmt)
	issues_by_metric = {row[0]: row[1] for row in metric_result.fetchall()}

	# Daily trend
	trend = []
	for i in range(days - 1, -1, -1):
		day = datetime.utcnow().date() - timedelta(days=i)
		next_day = day + timedelta(days=1)

		day_count_stmt = select(func.count()).select_from(QualityAssessment).where(
			and_(
				QualityAssessment.assessed_at >= day,
				QualityAssessment.assessed_at < next_day,
			)
		)
		day_count = await db_session.scalar(day_count_stmt) or 0

		day_passed_stmt = select(func.count()).select_from(QualityAssessment).where(
			and_(
				QualityAssessment.assessed_at >= day,
				QualityAssessment.assessed_at < next_day,
				QualityAssessment.passed == True,
			)
		)
		day_passed = await db_session.scalar(day_passed_stmt) or 0

		trend.append({
			"date": day.isoformat(),
			"total": day_count,
			"passed": day_passed,
			"failed": day_count - day_passed,
		})

	return schema.QualityStatsInfo(
		total_assessments=total,
		passed_count=passed,
		failed_count=failed,
		pass_rate=passed / total * 100 if total > 0 else 0.0,
		avg_quality_score=float(avg_score),
		issues_by_severity=issues_by_severity,
		issues_by_metric=issues_by_metric,
		trend_7d=trend,
	)


def _get_grade(score: float) -> str:
	"""Convert quality score to grade."""
	if score >= 90:
		return "excellent"
	elif score >= 75:
		return "good"
	elif score >= 60:
		return "acceptable"
	elif score >= 40:
		return "poor"
	else:
		return "unacceptable"


# VLM-powered quality assessment endpoints
@router.post("/assess/vlm")
async def assess_with_vlm(
	request: schema.VLMAssessmentRequest,
	user: require_scopes(scopes.NODE_VIEW),
) -> schema.VLMAssessmentResponse:
	"""
	Perform VLM-powered quality assessment on an image.

	Uses Qwen-VL to analyze document quality with AI-powered insights.
	Provides more comprehensive analysis than traditional CV-based assessment.
	"""
	from .vlm_assessor import VLMQualityAssessor, VLMQualityConfig
	from pathlib import Path

	config = VLMQualityConfig(
		ollama_base_url=request.ollama_base_url or "http://localhost:11434",
		model=request.model or "qwen2.5-vl:7b",
	)
	assessor = VLMQualityAssessor(config)

	if request.image_path:
		result = await assessor.assess_image(
			Path(request.image_path),
			include_traditional=request.include_traditional,
		)
	elif request.image_base64:
		result = await assessor.assess_from_bytes(
			base64.b64decode(request.image_base64),
			request.mime_type or "image/jpeg",
		)
	else:
		raise HTTPException(status_code=400, detail="Either image_path or image_base64 is required")

	return schema.VLMAssessmentResponse(
		document_type=result.get("document_type"),
		overall_quality_score=result.get("overall_quality_score"),
		quality_grade=result.get("quality_grade"),
		readability_score=result.get("readability_score"),
		scan_quality_score=result.get("scan_quality_score"),
		alignment_score=result.get("alignment_score"),
		content_integrity_score=result.get("content_integrity_score"),
		is_blank=result.get("is_blank", False),
		has_handwriting=result.get("has_handwriting", False),
		has_stamps_or_signatures=result.get("has_stamps_or_signatures", False),
		language_detected=result.get("language_detected"),
		issues=result.get("issues", []),
		recommendations=result.get("recommendations", []),
		summary=result.get("summary", ""),
		traditional_metrics=result.get("traditional_metrics"),
		blended_score=result.get("blended_score"),
		assessment_method=result.get("assessment_method", "vlm"),
		model=result.get("model"),
	)


@router.get("/vlm/health")
async def vlm_health_check(
	user: require_scopes(scopes.NODE_VIEW),
	ollama_base_url: str = "http://localhost:11434",
	model: str = "qwen2.5-vl:7b",
) -> dict:
	"""Check if VLM service is available and model is loaded."""
	from .vlm_assessor import VLMQualityAssessor, VLMQualityConfig

	config = VLMQualityConfig(ollama_base_url=ollama_base_url, model=model)
	assessor = VLMQualityAssessor(config)

	is_available = await assessor.health_check()

	return {
		"available": is_available,
		"model": model,
		"base_url": ollama_base_url,
	}
