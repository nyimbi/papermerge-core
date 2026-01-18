# (c) Copyright Datacraft, 2026
"""Service layer for Scanning Projects feature."""
import logging
from datetime import datetime, timedelta, date
from typing import Sequence
from uuid_extensions import uuid7str

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
	ScanningProjectModel,
	ScanningBatchModel,
	ScanningMilestoneModel,
	QualityControlSampleModel,
	ScanningResourceModel,
	ProjectPhaseModel,
	ScanningSesssionModel,
	ProgressSnapshotModel,
	DailyProjectMetricsModel,
	OperatorDailyMetricsModel,
	ProjectIssueModel,
)
from .views import (
	ScanningProject,
	ScanningProjectCreate,
	ScanningProjectUpdate,
	ScanningProjectStatus,
	ScanningBatch,
	ScanningBatchCreate,
	ScanningBatchUpdate,
	ScanningBatchStatus,
	ScanningMilestone,
	ScanningMilestoneCreate,
	ScanningMilestoneUpdate,
	MilestoneStatus,
	QualityControlSample,
	QualityControlSampleCreate,
	QualityControlSampleUpdate,
	QCReviewStatus,
	ScanningResource,
	ScanningResourceCreate,
	ScanningResourceUpdate,
	ScanningProjectMetrics,
	# New views
	ProjectPhase,
	ProjectPhaseCreate,
	ProjectPhaseUpdate,
	PhaseStatus,
	ScanningSession,
	ScanningSessionCreate,
	ScanningSessionEnd,
	ProgressSnapshot,
	DailyProjectMetrics,
	OperatorDailyMetrics,
	ProjectIssue,
	ProjectIssueCreate,
	ProjectIssueUpdate,
	IssueStatus,
)

logger = logging.getLogger(__name__)


def _log_project_action(action: str, project_id: str) -> str:
	return f"Scanning project {action}: {project_id[:8]}..."


# =====================================================
# Project Service
# =====================================================


async def get_scanning_projects(
	session: AsyncSession,
	tenant_id: str,
) -> Sequence[ScanningProject]:
	"""Get all scanning projects for a tenant."""
	stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.tenant_id == tenant_id
	).order_by(ScanningProjectModel.created_at.desc())
	result = await session.execute(stmt)
	return [ScanningProject.model_validate(row) for row in result.scalars().all()]


async def get_scanning_project(
	session: AsyncSession,
	project_id: str,
	tenant_id: str,
) -> ScanningProject | None:
	"""Get a single scanning project by ID."""
	stmt = select(ScanningProjectModel).where(
		and_(
			ScanningProjectModel.id == project_id,
			ScanningProjectModel.tenant_id == tenant_id,
		)
	)
	result = await session.execute(stmt)
	row = result.scalar_one_or_none()
	return ScanningProject.model_validate(row) if row else None


async def create_scanning_project(
	session: AsyncSession,
	tenant_id: str,
	data: ScanningProjectCreate,
) -> ScanningProject:
	"""Create a new scanning project."""
	project = ScanningProjectModel(
		id=uuid7str(),
		tenant_id=tenant_id,
		**data.model_dump(),
	)
	session.add(project)
	await session.commit()
	await session.refresh(project)
	logger.info(_log_project_action("created", project.id))
	return ScanningProject.model_validate(project)


async def update_scanning_project(
	session: AsyncSession,
	project_id: str,
	tenant_id: str,
	data: ScanningProjectUpdate,
) -> ScanningProject | None:
	"""Update a scanning project."""
	stmt = select(ScanningProjectModel).where(
		and_(
			ScanningProjectModel.id == project_id,
			ScanningProjectModel.tenant_id == tenant_id,
		)
	)
	result = await session.execute(stmt)
	project = result.scalar_one_or_none()
	if not project:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(project, key, value)
	project.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(project)
	logger.info(_log_project_action("updated", project.id))
	return ScanningProject.model_validate(project)


async def delete_scanning_project(
	session: AsyncSession,
	project_id: str,
	tenant_id: str,
) -> bool:
	"""Delete a scanning project and all associated data."""
	stmt = select(ScanningProjectModel).where(
		and_(
			ScanningProjectModel.id == project_id,
			ScanningProjectModel.tenant_id == tenant_id,
		)
	)
	result = await session.execute(stmt)
	project = result.scalar_one_or_none()
	if not project:
		return False

	await session.delete(project)
	await session.commit()
	logger.info(_log_project_action("deleted", project_id))
	return True


# =====================================================
# Batch Service
# =====================================================


async def get_project_batches(
	session: AsyncSession,
	project_id: str,
	tenant_id: str,
) -> Sequence[ScanningBatch]:
	"""Get all batches for a project."""
	stmt = select(ScanningBatchModel).where(
		ScanningBatchModel.project_id == project_id
	).order_by(ScanningBatchModel.batch_number)
	result = await session.execute(stmt)
	return [ScanningBatch.model_validate(row) for row in result.scalars().all()]


async def create_batch(
	session: AsyncSession,
	project_id: str,
	data: ScanningBatchCreate,
) -> ScanningBatch:
	"""Create a new batch for a project."""
	batch = ScanningBatchModel(
		id=uuid7str(),
		project_id=project_id,
		**data.model_dump(),
	)
	session.add(batch)
	await session.commit()
	await session.refresh(batch)
	return ScanningBatch.model_validate(batch)


async def update_batch(
	session: AsyncSession,
	batch_id: str,
	data: ScanningBatchUpdate,
) -> ScanningBatch | None:
	"""Update a batch."""
	stmt = select(ScanningBatchModel).where(ScanningBatchModel.id == batch_id)
	result = await session.execute(stmt)
	batch = result.scalar_one_or_none()
	if not batch:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(batch, key, value)
	batch.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(batch)
	return ScanningBatch.model_validate(batch)


async def start_batch_scan(
	session: AsyncSession,
	batch_id: str,
) -> ScanningBatch | None:
	"""Start scanning a batch."""
	stmt = select(ScanningBatchModel).where(ScanningBatchModel.id == batch_id)
	result = await session.execute(stmt)
	batch = result.scalar_one_or_none()
	if not batch:
		return None

	batch.status = ScanningBatchStatus.SCANNING
	batch.started_at = datetime.utcnow()
	batch.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(batch)
	return ScanningBatch.model_validate(batch)


async def complete_batch_scan(
	session: AsyncSession,
	batch_id: str,
	actual_pages: int,
) -> ScanningBatch | None:
	"""Complete scanning a batch."""
	stmt = select(ScanningBatchModel).where(ScanningBatchModel.id == batch_id)
	result = await session.execute(stmt)
	batch = result.scalar_one_or_none()
	if not batch:
		return None

	batch.status = ScanningBatchStatus.OCR_PROCESSING
	batch.actual_pages = actual_pages
	batch.scanned_pages = actual_pages
	batch.completed_at = datetime.utcnow()
	batch.updated_at = datetime.utcnow()

	# Update project totals
	project_stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.id == batch.project_id
	)
	project_result = await session.execute(project_stmt)
	project = project_result.scalar_one_or_none()
	if project:
		project.scanned_pages += actual_pages
		project.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(batch)
	return ScanningBatch.model_validate(batch)


# =====================================================
# Milestone Service
# =====================================================


async def get_project_milestones(
	session: AsyncSession,
	project_id: str,
) -> Sequence[ScanningMilestone]:
	"""Get all milestones for a project."""
	stmt = select(ScanningMilestoneModel).where(
		ScanningMilestoneModel.project_id == project_id
	).order_by(ScanningMilestoneModel.target_date)
	result = await session.execute(stmt)
	return [ScanningMilestone.model_validate(row) for row in result.scalars().all()]


async def create_milestone(
	session: AsyncSession,
	project_id: str,
	data: ScanningMilestoneCreate,
) -> ScanningMilestone:
	"""Create a new milestone."""
	milestone = ScanningMilestoneModel(
		id=uuid7str(),
		project_id=project_id,
		**data.model_dump(),
	)
	session.add(milestone)
	await session.commit()
	await session.refresh(milestone)
	return ScanningMilestone.model_validate(milestone)


async def update_milestone(
	session: AsyncSession,
	milestone_id: str,
	data: ScanningMilestoneUpdate,
) -> ScanningMilestone | None:
	"""Update a milestone."""
	stmt = select(ScanningMilestoneModel).where(ScanningMilestoneModel.id == milestone_id)
	result = await session.execute(stmt)
	milestone = result.scalar_one_or_none()
	if not milestone:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(milestone, key, value)

	await session.commit()
	await session.refresh(milestone)
	return ScanningMilestone.model_validate(milestone)


# =====================================================
# QC Service
# =====================================================


async def get_pending_qc_samples(
	session: AsyncSession,
	project_id: str,
) -> Sequence[QualityControlSample]:
	"""Get pending QC samples for a project."""
	# Get all batch IDs for this project
	batch_stmt = select(ScanningBatchModel.id).where(
		ScanningBatchModel.project_id == project_id
	)
	batch_result = await session.execute(batch_stmt)
	batch_ids = [row for row in batch_result.scalars().all()]

	stmt = select(QualityControlSampleModel).where(
		and_(
			QualityControlSampleModel.batch_id.in_(batch_ids),
			QualityControlSampleModel.review_status == QCReviewStatus.PENDING,
		)
	).order_by(QualityControlSampleModel.created_at)
	result = await session.execute(stmt)
	return [QualityControlSample.model_validate(row) for row in result.scalars().all()]


async def create_qc_sample(
	session: AsyncSession,
	data: QualityControlSampleCreate,
) -> QualityControlSample:
	"""Create a new QC sample."""
	sample = QualityControlSampleModel(
		id=uuid7str(),
		**data.model_dump(),
	)
	session.add(sample)
	await session.commit()
	await session.refresh(sample)
	return QualityControlSample.model_validate(sample)


async def update_qc_sample(
	session: AsyncSession,
	sample_id: str,
	reviewer_id: str,
	reviewer_name: str,
	data: QualityControlSampleUpdate,
) -> QualityControlSample | None:
	"""Update a QC sample with review results."""
	stmt = select(QualityControlSampleModel).where(QualityControlSampleModel.id == sample_id)
	result = await session.execute(stmt)
	sample = result.scalar_one_or_none()
	if not sample:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(sample, key, value)
	sample.reviewer_id = reviewer_id
	sample.reviewer_name = reviewer_name
	sample.reviewed_at = datetime.utcnow()

	# Update project verified/rejected counts if passed/failed
	if data.review_status in (QCReviewStatus.PASSED, QCReviewStatus.FAILED):
		batch_stmt = select(ScanningBatchModel).where(
			ScanningBatchModel.id == sample.batch_id
		)
		batch_result = await session.execute(batch_stmt)
		batch = batch_result.scalar_one_or_none()
		if batch:
			project_stmt = select(ScanningProjectModel).where(
				ScanningProjectModel.id == batch.project_id
			)
			project_result = await session.execute(project_stmt)
			project = project_result.scalar_one_or_none()
			if project:
				if data.review_status == QCReviewStatus.PASSED:
					project.verified_pages += 1
				else:
					project.rejected_pages += 1
				project.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(sample)
	return QualityControlSample.model_validate(sample)


# =====================================================
# Resource Service
# =====================================================


async def get_resources(
	session: AsyncSession,
	tenant_id: str,
) -> Sequence[ScanningResource]:
	"""Get all resources for a tenant."""
	stmt = select(ScanningResourceModel).where(
		ScanningResourceModel.tenant_id == tenant_id
	).order_by(ScanningResourceModel.type, ScanningResourceModel.name)
	result = await session.execute(stmt)
	return [ScanningResource.model_validate(row) for row in result.scalars().all()]


async def create_resource(
	session: AsyncSession,
	tenant_id: str,
	data: ScanningResourceCreate,
) -> ScanningResource:
	"""Create a new resource."""
	resource = ScanningResourceModel(
		id=uuid7str(),
		tenant_id=tenant_id,
		**data.model_dump(),
	)
	session.add(resource)
	await session.commit()
	await session.refresh(resource)
	return ScanningResource.model_validate(resource)


async def update_resource(
	session: AsyncSession,
	resource_id: str,
	tenant_id: str,
	data: ScanningResourceUpdate,
) -> ScanningResource | None:
	"""Update a resource."""
	stmt = select(ScanningResourceModel).where(
		and_(
			ScanningResourceModel.id == resource_id,
			ScanningResourceModel.tenant_id == tenant_id,
		)
	)
	result = await session.execute(stmt)
	resource = result.scalar_one_or_none()
	if not resource:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(resource, key, value)
	resource.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(resource)
	return ScanningResource.model_validate(resource)


async def delete_resource(
	session: AsyncSession,
	resource_id: str,
	tenant_id: str,
) -> bool:
	"""Delete a resource."""
	stmt = select(ScanningResourceModel).where(
		and_(
			ScanningResourceModel.id == resource_id,
			ScanningResourceModel.tenant_id == tenant_id,
		)
	)
	result = await session.execute(stmt)
	resource = result.scalar_one_or_none()
	if not resource:
		return False

	await session.delete(resource)
	await session.commit()
	return True


# =====================================================
# Metrics Service
# =====================================================


async def get_project_metrics(
	session: AsyncSession,
	project_id: str,
) -> ScanningProjectMetrics:
	"""Calculate metrics for a project."""
	# Get project
	project_stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.id == project_id
	)
	project_result = await session.execute(project_stmt)
	project = project_result.scalar_one_or_none()
	if not project:
		return ScanningProjectMetrics(project_id=project_id)

	# Get batch counts
	batch_stmt = select(
		func.count(ScanningBatchModel.id).label("total"),
		func.sum(
			func.case((ScanningBatchModel.status == ScanningBatchStatus.COMPLETED, 1), else_=0)
		).label("completed"),
		func.sum(
			func.case((ScanningBatchModel.status == ScanningBatchStatus.PENDING, 1), else_=0)
		).label("pending"),
		func.sum(
			func.case(
				(ScanningBatchModel.status.in_([
					ScanningBatchStatus.SCANNING,
					ScanningBatchStatus.OCR_PROCESSING,
					ScanningBatchStatus.QC_PENDING,
				]), 1),
				else_=0
			)
		).label("in_progress"),
	).where(ScanningBatchModel.project_id == project_id)
	batch_result = await session.execute(batch_stmt)
	batch_counts = batch_result.one()

	# Calculate average pages per day
	days_active = 1
	if project.start_date:
		days_active = max(1, (datetime.utcnow() - project.start_date).days)
	avg_pages_per_day = project.scanned_pages / days_active

	# Estimate completion date
	estimated_completion = None
	remaining_pages = project.total_estimated_pages - project.scanned_pages
	if avg_pages_per_day > 0 and remaining_pages > 0:
		days_remaining = remaining_pages / avg_pages_per_day
		estimated_completion = datetime.utcnow() + timedelta(days=days_remaining)

	# Get QC stats
	batch_ids_stmt = select(ScanningBatchModel.id).where(
		ScanningBatchModel.project_id == project_id
	)
	batch_ids_result = await session.execute(batch_ids_stmt)
	batch_ids = [row for row in batch_ids_result.scalars().all()]

	qc_stats = {"pass_rate": 0.0, "avg_quality": 0.0, "avg_ocr": None}
	if batch_ids:
		qc_stmt = select(
			func.count(QualityControlSampleModel.id).label("total"),
			func.sum(
				func.case((QualityControlSampleModel.review_status == QCReviewStatus.PASSED, 1), else_=0)
			).label("passed"),
			func.avg(QualityControlSampleModel.image_quality).label("avg_quality"),
			func.avg(QualityControlSampleModel.ocr_accuracy).label("avg_ocr"),
		).where(
			and_(
				QualityControlSampleModel.batch_id.in_(batch_ids),
				QualityControlSampleModel.review_status != QCReviewStatus.PENDING,
			)
		)
		qc_result = await session.execute(qc_stmt)
		qc_row = qc_result.one()
		if qc_row.total and qc_row.total > 0:
			qc_stats["pass_rate"] = (qc_row.passed or 0) / qc_row.total * 100
			qc_stats["avg_quality"] = float(qc_row.avg_quality or 0)
			qc_stats["avg_ocr"] = float(qc_row.avg_ocr) if qc_row.avg_ocr else None

	return ScanningProjectMetrics(
		project_id=project_id,
		total_batches=batch_counts.total or 0,
		completed_batches=batch_counts.completed or 0,
		pending_batches=batch_counts.pending or 0,
		in_progress_batches=batch_counts.in_progress or 0,
		total_pages=project.total_estimated_pages,
		scanned_pages=project.scanned_pages,
		verified_pages=project.verified_pages,
		rejected_pages=project.rejected_pages,
		average_pages_per_day=round(avg_pages_per_day, 1),
		estimated_completion_date=estimated_completion,
		qc_pass_rate=round(qc_stats["pass_rate"], 1),
		avg_image_quality=round(qc_stats["avg_quality"], 1),
		avg_ocr_accuracy=round(qc_stats["avg_ocr"], 1) if qc_stats["avg_ocr"] else None,
	)


# =====================================================
# Phase Service
# =====================================================


async def get_project_phases(
	session: AsyncSession,
	project_id: str,
) -> Sequence[ProjectPhase]:
	"""Get all phases for a project."""
	stmt = select(ProjectPhaseModel).where(
		ProjectPhaseModel.project_id == project_id
	).order_by(ProjectPhaseModel.sequence_order)
	result = await session.execute(stmt)
	return [ProjectPhase.model_validate(row) for row in result.scalars().all()]


async def create_phase(
	session: AsyncSession,
	project_id: str,
	data: ProjectPhaseCreate,
) -> ProjectPhase:
	"""Create a new phase."""
	phase = ProjectPhaseModel(
		id=uuid7str(),
		project_id=project_id,
		**data.model_dump(),
	)
	session.add(phase)
	await session.commit()
	await session.refresh(phase)
	return ProjectPhase.model_validate(phase)


async def update_phase(
	session: AsyncSession,
	phase_id: str,
	data: ProjectPhaseUpdate,
) -> ProjectPhase | None:
	"""Update a phase."""
	stmt = select(ProjectPhaseModel).where(ProjectPhaseModel.id == phase_id)
	result = await session.execute(stmt)
	phase = result.scalar_one_or_none()
	if not phase:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(phase, key, value)
	phase.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(phase)
	return ProjectPhase.model_validate(phase)


async def delete_phase(
	session: AsyncSession,
	phase_id: str,
) -> bool:
	"""Delete a phase."""
	stmt = select(ProjectPhaseModel).where(ProjectPhaseModel.id == phase_id)
	result = await session.execute(stmt)
	phase = result.scalar_one_or_none()
	if not phase:
		return False

	await session.delete(phase)
	await session.commit()
	return True


# =====================================================
# Session Service
# =====================================================


async def get_project_sessions(
	session: AsyncSession,
	project_id: str,
	active_only: bool = False,
) -> Sequence[ScanningSession]:
	"""Get scanning sessions for a project."""
	stmt = select(ScanningSesssionModel).where(
		ScanningSesssionModel.project_id == project_id
	)
	if active_only:
		stmt = stmt.where(ScanningSesssionModel.ended_at.is_(None))
	stmt = stmt.order_by(ScanningSesssionModel.started_at.desc())
	result = await session.execute(stmt)
	return [ScanningSession.model_validate(row) for row in result.scalars().all()]


async def start_session(
	session: AsyncSession,
	project_id: str,
	data: ScanningSessionCreate,
) -> ScanningSession:
	"""Start a new scanning session."""
	scan_session = ScanningSesssionModel(
		id=uuid7str(),
		project_id=project_id,
		**data.model_dump(),
		started_at=datetime.utcnow(),
	)
	session.add(scan_session)
	await session.commit()
	await session.refresh(scan_session)
	logger.info(f"Started scanning session {scan_session.id[:8]}...")
	return ScanningSession.model_validate(scan_session)


async def end_session(
	session: AsyncSession,
	session_id: str,
	data: ScanningSessionEnd,
) -> ScanningSession | None:
	"""End a scanning session."""
	stmt = select(ScanningSesssionModel).where(ScanningSesssionModel.id == session_id)
	result = await session.execute(stmt)
	scan_session = result.scalar_one_or_none()
	if not scan_session:
		return None

	now = datetime.utcnow()
	scan_session.ended_at = now
	scan_session.documents_scanned = data.documents_scanned
	scan_session.pages_scanned = data.pages_scanned
	scan_session.pages_rejected = data.pages_rejected
	if data.notes:
		scan_session.notes = data.notes

	# Calculate pages per hour
	duration_hours = (now - scan_session.started_at).total_seconds() / 3600
	if duration_hours > 0:
		scan_session.average_pages_per_hour = data.pages_scanned / duration_hours

	# Update project totals
	project_stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.id == scan_session.project_id
	)
	project_result = await session.execute(project_stmt)
	project = project_result.scalar_one_or_none()
	if project:
		project.scanned_pages += data.pages_scanned
		project.rejected_pages += data.pages_rejected
		project.updated_at = now

	await session.commit()
	await session.refresh(scan_session)
	logger.info(f"Ended scanning session {scan_session.id[:8]}... ({data.pages_scanned} pages)")
	return ScanningSession.model_validate(scan_session)


# =====================================================
# Issue Service
# =====================================================


async def get_project_issues(
	session: AsyncSession,
	project_id: str,
	open_only: bool = False,
) -> Sequence[ProjectIssue]:
	"""Get issues for a project."""
	stmt = select(ProjectIssueModel).where(ProjectIssueModel.project_id == project_id)
	if open_only:
		stmt = stmt.where(ProjectIssueModel.status.in_(["open", "in_progress"]))
	stmt = stmt.order_by(ProjectIssueModel.created_at.desc())
	result = await session.execute(stmt)
	return [ProjectIssue.model_validate(row) for row in result.scalars().all()]


async def create_issue(
	session: AsyncSession,
	project_id: str,
	reporter_id: str,
	reporter_name: str,
	data: ProjectIssueCreate,
) -> ProjectIssue:
	"""Create a new issue."""
	issue = ProjectIssueModel(
		id=uuid7str(),
		project_id=project_id,
		reported_by_id=reporter_id,
		reported_by_name=reporter_name,
		**data.model_dump(),
	)
	session.add(issue)
	await session.commit()
	await session.refresh(issue)
	logger.info(f"Created issue {issue.id[:8]}... ({issue.title})")
	return ProjectIssue.model_validate(issue)


async def update_issue(
	session: AsyncSession,
	issue_id: str,
	data: ProjectIssueUpdate,
) -> ProjectIssue | None:
	"""Update an issue."""
	stmt = select(ProjectIssueModel).where(ProjectIssueModel.id == issue_id)
	result = await session.execute(stmt)
	issue = result.scalar_one_or_none()
	if not issue:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(issue, key, value)
	issue.updated_at = datetime.utcnow()

	# Set resolved_at if status changed to resolved/closed
	if data.status in (IssueStatus.RESOLVED, IssueStatus.CLOSED) and not issue.resolved_at:
		issue.resolved_at = datetime.utcnow()

	await session.commit()
	await session.refresh(issue)
	return ProjectIssue.model_validate(issue)


# =====================================================
# Snapshot Service
# =====================================================


async def create_snapshot(
	session: AsyncSession,
	project_id: str,
) -> ProgressSnapshot:
	"""Create a progress snapshot for a project."""
	# Get current project state
	project_stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.id == project_id
	)
	project_result = await session.execute(project_stmt)
	project = project_result.scalar_one()

	# Count active sessions
	active_stmt = select(func.count(ScanningSesssionModel.id)).where(
		and_(
			ScanningSesssionModel.project_id == project_id,
			ScanningSesssionModel.ended_at.is_(None),
		)
	)
	active_result = await session.execute(active_stmt)
	active_operators = active_result.scalar() or 0

	# Get average quality
	batch_ids_stmt = select(ScanningBatchModel.id).where(
		ScanningBatchModel.project_id == project_id
	)
	batch_ids_result = await session.execute(batch_ids_stmt)
	batch_ids = [r for r in batch_ids_result.scalars().all()]

	avg_quality = None
	if batch_ids:
		qc_stmt = select(func.avg(QualityControlSampleModel.image_quality)).where(
			QualityControlSampleModel.batch_id.in_(batch_ids)
		)
		qc_result = await session.execute(qc_stmt)
		avg_quality = qc_result.scalar()

	# Calculate pages per hour from recent sessions
	one_hour_ago = datetime.utcnow() - timedelta(hours=1)
	recent_stmt = select(func.sum(ScanningSesssionModel.pages_scanned)).where(
		and_(
			ScanningSesssionModel.project_id == project_id,
			ScanningSesssionModel.ended_at >= one_hour_ago,
		)
	)
	recent_result = await session.execute(recent_stmt)
	pages_last_hour = recent_result.scalar() or 0

	snapshot = ProgressSnapshotModel(
		id=uuid7str(),
		project_id=project_id,
		snapshot_time=datetime.utcnow(),
		total_pages_scanned=project.scanned_pages,
		pages_verified=project.verified_pages,
		pages_rejected=project.rejected_pages,
		pages_per_hour=float(pages_last_hour),
		active_operators=active_operators,
		active_scanners=active_operators,  # Simplified
		average_quality_score=float(avg_quality) if avg_quality else None,
	)
	session.add(snapshot)
	await session.commit()
	await session.refresh(snapshot)
	return ProgressSnapshot.model_validate(snapshot)


async def get_project_snapshots(
	session: AsyncSession,
	project_id: str,
	limit: int = 100,
) -> Sequence[ProgressSnapshot]:
	"""Get progress snapshots for a project."""
	stmt = select(ProgressSnapshotModel).where(
		ProgressSnapshotModel.project_id == project_id
	).order_by(ProgressSnapshotModel.snapshot_time.desc()).limit(limit)
	result = await session.execute(stmt)
	return [ProgressSnapshot.model_validate(row) for row in result.scalars().all()]


# =====================================================
# Daily Metrics Service
# =====================================================


async def get_daily_metrics(
	session: AsyncSession,
	project_id: str,
	start_date: date | None = None,
	end_date: date | None = None,
) -> Sequence[DailyProjectMetrics]:
	"""Get daily project metrics."""
	stmt = select(DailyProjectMetricsModel).where(
		DailyProjectMetricsModel.project_id == project_id
	)
	if start_date:
		stmt = stmt.where(DailyProjectMetricsModel.metric_date >= datetime.combine(start_date, datetime.min.time()))
	if end_date:
		stmt = stmt.where(DailyProjectMetricsModel.metric_date <= datetime.combine(end_date, datetime.max.time()))
	stmt = stmt.order_by(DailyProjectMetricsModel.metric_date.desc())
	result = await session.execute(stmt)
	return [DailyProjectMetrics.model_validate(row) for row in result.scalars().all()]


async def get_operator_metrics(
	session: AsyncSession,
	project_id: str,
	operator_id: str | None = None,
	start_date: date | None = None,
	end_date: date | None = None,
) -> Sequence[OperatorDailyMetrics]:
	"""Get operator daily metrics."""
	stmt = select(OperatorDailyMetricsModel).where(
		OperatorDailyMetricsModel.project_id == project_id
	)
	if operator_id:
		stmt = stmt.where(OperatorDailyMetricsModel.operator_id == operator_id)
	if start_date:
		stmt = stmt.where(OperatorDailyMetricsModel.metric_date >= datetime.combine(start_date, datetime.min.time()))
	if end_date:
		stmt = stmt.where(OperatorDailyMetricsModel.metric_date <= datetime.combine(end_date, datetime.max.time()))
	stmt = stmt.order_by(OperatorDailyMetricsModel.metric_date.desc())
	result = await session.execute(stmt)
	return [OperatorDailyMetrics.model_validate(row) for row in result.scalars().all()]
