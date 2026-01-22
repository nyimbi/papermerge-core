# (c) Copyright Datacraft, 2026
"""Service layer for Scanning Projects feature."""
import logging
from datetime import datetime, timedelta, date
from typing import Sequence
from uuid import UUID
from papermerge.core.utils.uuid_compat import uuid7, uuid7str

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
	# Enterprise-scale models
	SubProjectModel,
	ScanningLocationModel,
	ShiftModel,
	ShiftAssignmentModel,
	ProjectCostModel,
	ProjectBudgetModel,
	SLAModel,
	SLAAlertModel,
	EquipmentMaintenanceModel,
	OperatorCertificationModel,
	CapacityPlanModel,
	DocumentTypeDistributionModel,
	BatchPriorityQueueModel,
	ProjectContractModel,
	WorkloadForecastModel,
	ProjectCheckpointModel,
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
	# Enterprise-scale views
	SubProject,
	SubProjectCreate,
	SubProjectUpdate,
	SubProjectStatus,
	ScanningLocation,
	ScanningLocationCreate,
	ScanningLocationUpdate,
	Shift,
	ShiftCreate,
	ShiftUpdate,
	ShiftAssignment,
	ShiftAssignmentCreate,
	ShiftAssignmentBulkCreate,
	ProjectCost,
	ProjectCostCreate,
	ProjectBudget,
	ProjectBudgetCreate,
	ProjectBudgetUpdate,
	CostSummary,
	CostType,
	SLA,
	SLACreate,
	SLAUpdate,
	SLAAlert,
	SLAStatus,
	EquipmentMaintenance,
	EquipmentMaintenanceCreate,
	EquipmentMaintenanceUpdate,
	MaintenanceStatus,
	OperatorCertification,
	OperatorCertificationCreate,
	OperatorCertificationUpdate,
	CapacityPlan,
	CapacityPlanCreate,
	DocumentTypeDistribution,
	DocumentTypeDistributionCreate,
	DocumentTypeDistributionUpdate,
	BatchPriority,
	BatchPriorityCreate,
	BatchPriorityUpdate,
	ProjectContract,
	ProjectContractCreate,
	ProjectContractUpdate,
	WorkloadForecast,
	ProjectCheckpoint,
	ProjectCheckpointCreate,
	ProjectCheckpointUpdate,
	CheckpointStatus,
	# Bulk operations
	BulkBatchImport,
	BulkBatchUpdate,
	BulkOperationResult,
	# Dashboard and analytics
	ProjectDashboard,
	BurndownChart,
	BurndownDataPoint,
	VelocityChart,
	VelocityDataPoint,
	LocationMetrics,
	MultiLocationDashboard,
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
	user_id: str,
	data: ScanningProjectCreate,
) -> ScanningProject:
	"""Create a new scanning project."""
	project = ScanningProjectModel(
		id=uuid7(),
		tenant_id=UUID(tenant_id),
		created_by=UUID(user_id),
		updated_by=UUID(user_id),
		**data.model_dump(),
	)
	session.add(project)
	await session.commit()
	await session.refresh(project)
	logger.info(_log_project_action("created", str(project.id)))
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


# =====================================================
# Sub-Project Service
# =====================================================


async def get_sub_projects(
	session: AsyncSession,
	parent_project_id: str,
) -> Sequence[SubProject]:
	"""Get all sub-projects for a parent project."""
	stmt = select(SubProjectModel).where(
		SubProjectModel.parent_project_id == parent_project_id
	).order_by(SubProjectModel.priority.desc(), SubProjectModel.code)
	result = await session.execute(stmt)
	return [SubProject.model_validate(row) for row in result.scalars().all()]


async def get_sub_project(
	session: AsyncSession,
	sub_project_id: str,
) -> SubProject | None:
	"""Get a single sub-project by ID."""
	stmt = select(SubProjectModel).where(SubProjectModel.id == sub_project_id)
	result = await session.execute(stmt)
	row = result.scalar_one_or_none()
	return SubProject.model_validate(row) if row else None


async def create_sub_project(
	session: AsyncSession,
	parent_project_id: str,
	data: SubProjectCreate,
) -> SubProject:
	"""Create a new sub-project."""
	sub_project = SubProjectModel(
		id=uuid7str(),
		parent_project_id=parent_project_id,
		**data.model_dump(),
	)
	session.add(sub_project)
	await session.commit()
	await session.refresh(sub_project)
	logger.info(f"Created sub-project {sub_project.code}")
	return SubProject.model_validate(sub_project)


async def update_sub_project(
	session: AsyncSession,
	sub_project_id: str,
	data: SubProjectUpdate,
) -> SubProject | None:
	"""Update a sub-project."""
	stmt = select(SubProjectModel).where(SubProjectModel.id == sub_project_id)
	result = await session.execute(stmt)
	sub_project = result.scalar_one_or_none()
	if not sub_project:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(sub_project, key, value)
	sub_project.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(sub_project)
	return SubProject.model_validate(sub_project)


async def delete_sub_project(
	session: AsyncSession,
	sub_project_id: str,
) -> bool:
	"""Delete a sub-project."""
	stmt = select(SubProjectModel).where(SubProjectModel.id == sub_project_id)
	result = await session.execute(stmt)
	sub_project = result.scalar_one_or_none()
	if not sub_project:
		return False

	await session.delete(sub_project)
	await session.commit()
	return True


# =====================================================
# Location Service
# =====================================================


async def get_locations(
	session: AsyncSession,
	tenant_id: str,
	active_only: bool = True,
) -> Sequence[ScanningLocation]:
	"""Get all scanning locations for a tenant."""
	stmt = select(ScanningLocationModel).where(
		ScanningLocationModel.tenant_id == tenant_id
	)
	if active_only:
		stmt = stmt.where(ScanningLocationModel.is_active == True)
	stmt = stmt.order_by(ScanningLocationModel.name)
	result = await session.execute(stmt)
	return [ScanningLocation.model_validate(row) for row in result.scalars().all()]


async def get_location(
	session: AsyncSession,
	location_id: str,
	tenant_id: str,
) -> ScanningLocation | None:
	"""Get a single location by ID."""
	stmt = select(ScanningLocationModel).where(
		and_(
			ScanningLocationModel.id == location_id,
			ScanningLocationModel.tenant_id == tenant_id,
		)
	)
	result = await session.execute(stmt)
	row = result.scalar_one_or_none()
	return ScanningLocation.model_validate(row) if row else None


async def create_location(
	session: AsyncSession,
	tenant_id: str,
	data: ScanningLocationCreate,
) -> ScanningLocation:
	"""Create a new scanning location."""
	location = ScanningLocationModel(
		id=uuid7str(),
		tenant_id=tenant_id,
		**data.model_dump(),
	)
	session.add(location)
	await session.commit()
	await session.refresh(location)
	logger.info(f"Created location {location.code}")
	return ScanningLocation.model_validate(location)


async def update_location(
	session: AsyncSession,
	location_id: str,
	tenant_id: str,
	data: ScanningLocationUpdate,
) -> ScanningLocation | None:
	"""Update a location."""
	stmt = select(ScanningLocationModel).where(
		and_(
			ScanningLocationModel.id == location_id,
			ScanningLocationModel.tenant_id == tenant_id,
		)
	)
	result = await session.execute(stmt)
	location = result.scalar_one_or_none()
	if not location:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(location, key, value)
	location.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(location)
	return ScanningLocation.model_validate(location)


async def delete_location(
	session: AsyncSession,
	location_id: str,
	tenant_id: str,
) -> bool:
	"""Delete a location."""
	stmt = select(ScanningLocationModel).where(
		and_(
			ScanningLocationModel.id == location_id,
			ScanningLocationModel.tenant_id == tenant_id,
		)
	)
	result = await session.execute(stmt)
	location = result.scalar_one_or_none()
	if not location:
		return False

	await session.delete(location)
	await session.commit()
	return True


# =====================================================
# Shift Service
# =====================================================


async def get_shifts(
	session: AsyncSession,
	tenant_id: str,
	location_id: str | None = None,
	active_only: bool = True,
) -> Sequence[Shift]:
	"""Get all shifts for a tenant, optionally filtered by location."""
	stmt = select(ShiftModel).where(ShiftModel.tenant_id == tenant_id)
	if location_id:
		stmt = stmt.where(ShiftModel.location_id == location_id)
	if active_only:
		stmt = stmt.where(ShiftModel.is_active == True)
	stmt = stmt.order_by(ShiftModel.start_time)
	result = await session.execute(stmt)
	return [Shift.model_validate(row) for row in result.scalars().all()]


async def create_shift(
	session: AsyncSession,
	tenant_id: str,
	data: ShiftCreate,
) -> Shift:
	"""Create a new shift."""
	shift = ShiftModel(
		id=uuid7str(),
		tenant_id=tenant_id,
		**data.model_dump(),
	)
	session.add(shift)
	await session.commit()
	await session.refresh(shift)
	logger.info(f"Created shift {shift.name}")
	return Shift.model_validate(shift)


async def update_shift(
	session: AsyncSession,
	shift_id: str,
	tenant_id: str,
	data: ShiftUpdate,
) -> Shift | None:
	"""Update a shift."""
	stmt = select(ShiftModel).where(
		and_(
			ShiftModel.id == shift_id,
			ShiftModel.tenant_id == tenant_id,
		)
	)
	result = await session.execute(stmt)
	shift = result.scalar_one_or_none()
	if not shift:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(shift, key, value)

	await session.commit()
	await session.refresh(shift)
	return Shift.model_validate(shift)


async def create_shift_assignment(
	session: AsyncSession,
	data: ShiftAssignmentCreate,
) -> ShiftAssignment:
	"""Assign an operator to a shift."""
	assignment = ShiftAssignmentModel(
		id=uuid7str(),
		**data.model_dump(),
	)
	session.add(assignment)
	await session.commit()
	await session.refresh(assignment)
	return ShiftAssignment.model_validate(assignment)


async def get_shift_assignments(
	session: AsyncSession,
	shift_id: str | None = None,
	operator_id: str | None = None,
	assignment_date: date | None = None,
) -> Sequence[ShiftAssignment]:
	"""Get shift assignments with optional filters."""
	stmt = select(ShiftAssignmentModel)
	if shift_id:
		stmt = stmt.where(ShiftAssignmentModel.shift_id == shift_id)
	if operator_id:
		stmt = stmt.where(ShiftAssignmentModel.operator_id == operator_id)
	if assignment_date:
		stmt = stmt.where(
			ShiftAssignmentModel.assignment_date >= datetime.combine(assignment_date, datetime.min.time())
		).where(
			ShiftAssignmentModel.assignment_date <= datetime.combine(assignment_date, datetime.max.time())
		)
	stmt = stmt.order_by(ShiftAssignmentModel.assignment_date.desc())
	result = await session.execute(stmt)
	return [ShiftAssignment.model_validate(row) for row in result.scalars().all()]


async def bulk_create_shift_assignments(
	session: AsyncSession,
	data: ShiftAssignmentBulkCreate,
) -> list[ShiftAssignment]:
	"""Bulk create shift assignments."""
	assignments = []
	for assignment_data in data.assignments:
		assignment = ShiftAssignmentModel(
			id=uuid7str(),
			**assignment_data.model_dump(),
		)
		session.add(assignment)
		assignments.append(assignment)

	await session.commit()
	for assignment in assignments:
		await session.refresh(assignment)

	return [ShiftAssignment.model_validate(a) for a in assignments]


# =====================================================
# Cost Tracking Service
# =====================================================


async def add_project_cost(
	session: AsyncSession,
	project_id: str,
	data: ProjectCostCreate,
) -> ProjectCost:
	"""Add a cost entry to a project."""
	total_cost = data.quantity * data.unit_cost
	cost = ProjectCostModel(
		id=uuid7str(),
		project_id=project_id,
		total_cost=total_cost,
		**data.model_dump(),
	)
	session.add(cost)

	# Update budget spent_to_date if budget exists
	budget_stmt = select(ProjectBudgetModel).where(
		ProjectBudgetModel.project_id == project_id
	)
	budget_result = await session.execute(budget_stmt)
	budget = budget_result.scalar_one_or_none()
	if budget:
		budget.spent_to_date += total_cost
		budget.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(cost)
	return ProjectCost.model_validate(cost)


async def get_project_costs(
	session: AsyncSession,
	project_id: str,
	cost_type: CostType | None = None,
	start_date: date | None = None,
	end_date: date | None = None,
) -> Sequence[ProjectCost]:
	"""Get project costs with optional filters."""
	stmt = select(ProjectCostModel).where(ProjectCostModel.project_id == project_id)
	if cost_type:
		stmt = stmt.where(ProjectCostModel.cost_type == cost_type.value)
	if start_date:
		stmt = stmt.where(ProjectCostModel.cost_date >= datetime.combine(start_date, datetime.min.time()))
	if end_date:
		stmt = stmt.where(ProjectCostModel.cost_date <= datetime.combine(end_date, datetime.max.time()))
	stmt = stmt.order_by(ProjectCostModel.cost_date.desc())
	result = await session.execute(stmt)
	return [ProjectCost.model_validate(row) for row in result.scalars().all()]


async def get_cost_summary(
	session: AsyncSession,
	project_id: str,
) -> CostSummary:
	"""Get cost summary for a project."""
	# Get project
	project_stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.id == project_id
	)
	project_result = await session.execute(project_stmt)
	project = project_result.scalar_one_or_none()

	# Get budget
	budget_stmt = select(ProjectBudgetModel).where(
		ProjectBudgetModel.project_id == project_id
	)
	budget_result = await session.execute(budget_stmt)
	budget = budget_result.scalar_one_or_none()

	# Get costs by type
	costs_stmt = select(
		ProjectCostModel.cost_type,
		func.sum(ProjectCostModel.total_cost).label("total"),
	).where(
		ProjectCostModel.project_id == project_id
	).group_by(ProjectCostModel.cost_type)
	costs_result = await session.execute(costs_stmt)
	costs_by_type = {row.cost_type: row.total for row in costs_result}

	total_spent = sum(costs_by_type.values())
	budget_remaining = (budget.total_budget - total_spent) if budget else 0
	budget_utilization = (total_spent / budget.total_budget * 100) if budget and budget.total_budget > 0 else 0
	cost_per_page = (total_spent / project.scanned_pages) if project and project.scanned_pages > 0 else 0

	# Project total cost based on current rate
	projected_total = 0.0
	if project and project.total_estimated_pages > 0 and cost_per_page > 0:
		projected_total = cost_per_page * project.total_estimated_pages

	return CostSummary(
		project_id=project_id,
		total_spent=total_spent,
		labor_spent=costs_by_type.get("labor", 0.0),
		equipment_spent=costs_by_type.get("equipment", 0.0),
		materials_spent=costs_by_type.get("materials", 0.0),
		storage_spent=costs_by_type.get("storage", 0.0),
		other_spent=costs_by_type.get("other", 0.0),
		budget_remaining=budget_remaining,
		budget_utilization_percent=round(budget_utilization, 1),
		cost_per_page=round(cost_per_page, 4),
		projected_total_cost=round(projected_total, 2),
		currency=budget.currency if budget else "USD",
	)


async def create_budget(
	session: AsyncSession,
	project_id: str,
	data: ProjectBudgetCreate,
) -> ProjectBudget:
	"""Create a project budget."""
	budget = ProjectBudgetModel(
		id=uuid7str(),
		project_id=project_id,
		**data.model_dump(),
	)
	session.add(budget)
	await session.commit()
	await session.refresh(budget)
	logger.info(f"Created budget {budget.budget_name} for project {project_id[:8]}...")
	return ProjectBudget.model_validate(budget)


async def get_budget(
	session: AsyncSession,
	project_id: str,
) -> ProjectBudget | None:
	"""Get budget for a project."""
	stmt = select(ProjectBudgetModel).where(ProjectBudgetModel.project_id == project_id)
	result = await session.execute(stmt)
	row = result.scalar_one_or_none()
	return ProjectBudget.model_validate(row) if row else None


async def update_budget(
	session: AsyncSession,
	budget_id: str,
	data: ProjectBudgetUpdate,
	approver_id: str | None = None,
) -> ProjectBudget | None:
	"""Update a project budget."""
	stmt = select(ProjectBudgetModel).where(ProjectBudgetModel.id == budget_id)
	result = await session.execute(stmt)
	budget = result.scalar_one_or_none()
	if not budget:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(budget, key, value)

	if data.is_approved and approver_id:
		budget.approved_by_id = approver_id
		budget.approved_at = datetime.utcnow()

	budget.updated_at = datetime.utcnow()
	await session.commit()
	await session.refresh(budget)
	return ProjectBudget.model_validate(budget)


# =====================================================
# SLA Service
# =====================================================


async def get_project_slas(
	session: AsyncSession,
	project_id: str,
) -> Sequence[SLA]:
	"""Get all SLAs for a project."""
	stmt = select(SLAModel).where(
		SLAModel.project_id == project_id
	).order_by(SLAModel.start_date)
	result = await session.execute(stmt)
	return [SLA.model_validate(row) for row in result.scalars().all()]


async def create_sla(
	session: AsyncSession,
	project_id: str,
	data: SLACreate,
) -> SLA:
	"""Create a new SLA."""
	sla = SLAModel(
		id=uuid7str(),
		project_id=project_id,
		**data.model_dump(),
	)
	session.add(sla)
	await session.commit()
	await session.refresh(sla)
	logger.info(f"Created SLA {sla.name}")
	return SLA.model_validate(sla)


async def update_sla(
	session: AsyncSession,
	sla_id: str,
	data: SLAUpdate,
) -> SLA | None:
	"""Update an SLA."""
	stmt = select(SLAModel).where(SLAModel.id == sla_id)
	result = await session.execute(stmt)
	sla = result.scalar_one_or_none()
	if not sla:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(sla, key, value)

	await session.commit()
	await session.refresh(sla)
	return SLA.model_validate(sla)


async def check_sla_status(
	session: AsyncSession,
	sla_id: str,
	current_value: float,
) -> SLA | None:
	"""Check and update SLA status based on current value."""
	stmt = select(SLAModel).where(SLAModel.id == sla_id)
	result = await session.execute(stmt)
	sla = result.scalar_one_or_none()
	if not sla:
		return None

	sla.current_value = current_value
	sla.last_checked_at = datetime.utcnow()

	# Determine status
	old_status = sla.status
	if sla.sla_type in ("completion", "quality", "throughput"):
		# Higher is better
		if current_value < sla.target_value:
			if sla.threshold_critical and current_value <= sla.threshold_critical:
				sla.status = "breached"
			elif sla.threshold_warning and current_value <= sla.threshold_warning:
				sla.status = "at_risk"
			else:
				sla.status = "at_risk"
		else:
			sla.status = "on_track"
	else:  # turnaround - lower is better
		if current_value > sla.target_value:
			if sla.threshold_critical and current_value >= sla.threshold_critical:
				sla.status = "breached"
			elif sla.threshold_warning and current_value >= sla.threshold_warning:
				sla.status = "at_risk"
			else:
				sla.status = "at_risk"
		else:
			sla.status = "on_track"

	# Create alert if status changed to at_risk or breached
	if sla.status != old_status and sla.status in ("at_risk", "breached"):
		alert_type = "critical" if sla.status == "breached" else "warning"
		alert = SLAAlertModel(
			id=uuid7str(),
			sla_id=sla_id,
			alert_type=alert_type,
			message=f"SLA '{sla.name}' is {sla.status}: current={current_value}, target={sla.target_value}",
			current_value=current_value,
			target_value=sla.target_value,
		)
		session.add(alert)

		if sla.status == "breached" and not sla.breached_at:
			sla.breached_at = datetime.utcnow()

	await session.commit()
	await session.refresh(sla)
	return SLA.model_validate(sla)


async def get_sla_alerts(
	session: AsyncSession,
	sla_id: str | None = None,
	project_id: str | None = None,
	unacknowledged_only: bool = False,
) -> Sequence[SLAAlert]:
	"""Get SLA alerts."""
	if project_id:
		# Get all SLA IDs for project
		sla_stmt = select(SLAModel.id).where(SLAModel.project_id == project_id)
		sla_result = await session.execute(sla_stmt)
		sla_ids = [r for r in sla_result.scalars().all()]
		stmt = select(SLAAlertModel).where(SLAAlertModel.sla_id.in_(sla_ids))
	elif sla_id:
		stmt = select(SLAAlertModel).where(SLAAlertModel.sla_id == sla_id)
	else:
		stmt = select(SLAAlertModel)

	if unacknowledged_only:
		stmt = stmt.where(SLAAlertModel.acknowledged_at.is_(None))

	stmt = stmt.order_by(SLAAlertModel.alert_time.desc())
	result = await session.execute(stmt)
	return [SLAAlert.model_validate(row) for row in result.scalars().all()]


async def acknowledge_sla_alert(
	session: AsyncSession,
	alert_id: str,
	user_id: str,
	resolution_notes: str | None = None,
) -> SLAAlert | None:
	"""Acknowledge an SLA alert."""
	stmt = select(SLAAlertModel).where(SLAAlertModel.id == alert_id)
	result = await session.execute(stmt)
	alert = result.scalar_one_or_none()
	if not alert:
		return None

	alert.acknowledged_by_id = user_id
	alert.acknowledged_at = datetime.utcnow()
	if resolution_notes:
		alert.resolution_notes = resolution_notes

	await session.commit()
	await session.refresh(alert)
	return SLAAlert.model_validate(alert)


# =====================================================
# Equipment Maintenance Service
# =====================================================


async def get_maintenance_schedule(
	session: AsyncSession,
	resource_id: str | None = None,
	status: MaintenanceStatus | None = None,
	upcoming_days: int | None = None,
) -> Sequence[EquipmentMaintenance]:
	"""Get maintenance schedule with optional filters."""
	stmt = select(EquipmentMaintenanceModel)
	if resource_id:
		stmt = stmt.where(EquipmentMaintenanceModel.resource_id == resource_id)
	if status:
		stmt = stmt.where(EquipmentMaintenanceModel.status == status.value)
	if upcoming_days:
		cutoff = datetime.utcnow() + timedelta(days=upcoming_days)
		stmt = stmt.where(EquipmentMaintenanceModel.scheduled_date <= cutoff)
		stmt = stmt.where(EquipmentMaintenanceModel.status == "scheduled")
	stmt = stmt.order_by(EquipmentMaintenanceModel.scheduled_date)
	result = await session.execute(stmt)
	return [EquipmentMaintenance.model_validate(row) for row in result.scalars().all()]


async def schedule_maintenance(
	session: AsyncSession,
	data: EquipmentMaintenanceCreate,
) -> EquipmentMaintenance:
	"""Schedule equipment maintenance."""
	maintenance = EquipmentMaintenanceModel(
		id=uuid7str(),
		**data.model_dump(),
	)
	session.add(maintenance)
	await session.commit()
	await session.refresh(maintenance)
	logger.info(f"Scheduled maintenance: {maintenance.title}")
	return EquipmentMaintenance.model_validate(maintenance)


async def update_maintenance(
	session: AsyncSession,
	maintenance_id: str,
	data: EquipmentMaintenanceUpdate,
) -> EquipmentMaintenance | None:
	"""Update maintenance record."""
	stmt = select(EquipmentMaintenanceModel).where(EquipmentMaintenanceModel.id == maintenance_id)
	result = await session.execute(stmt)
	maintenance = result.scalar_one_or_none()
	if not maintenance:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(maintenance, key, value)

	# If completing, set completed_date
	if data.status == MaintenanceStatus.COMPLETED and not maintenance.completed_date:
		maintenance.completed_date = datetime.utcnow()

	await session.commit()
	await session.refresh(maintenance)
	return EquipmentMaintenance.model_validate(maintenance)


# =====================================================
# Operator Certification Service
# =====================================================


async def get_operator_certifications(
	session: AsyncSession,
	operator_id: str | None = None,
	certification_type: str | None = None,
	active_only: bool = True,
) -> Sequence[OperatorCertification]:
	"""Get operator certifications."""
	stmt = select(OperatorCertificationModel)
	if operator_id:
		stmt = stmt.where(OperatorCertificationModel.operator_id == operator_id)
	if certification_type:
		stmt = stmt.where(OperatorCertificationModel.certification_type == certification_type)
	if active_only:
		stmt = stmt.where(OperatorCertificationModel.is_active == True)
	stmt = stmt.order_by(OperatorCertificationModel.issued_date.desc())
	result = await session.execute(stmt)
	return [OperatorCertification.model_validate(row) for row in result.scalars().all()]


async def create_certification(
	session: AsyncSession,
	data: OperatorCertificationCreate,
) -> OperatorCertification:
	"""Create an operator certification."""
	cert = OperatorCertificationModel(
		id=uuid7str(),
		**data.model_dump(),
	)
	session.add(cert)
	await session.commit()
	await session.refresh(cert)
	logger.info(f"Created certification {cert.certification_name} for operator {cert.operator_id[:8]}...")
	return OperatorCertification.model_validate(cert)


async def update_certification(
	session: AsyncSession,
	certification_id: str,
	data: OperatorCertificationUpdate,
) -> OperatorCertification | None:
	"""Update an operator certification."""
	stmt = select(OperatorCertificationModel).where(
		OperatorCertificationModel.id == certification_id
	)
	result = await session.execute(stmt)
	cert = result.scalar_one_or_none()
	if not cert:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(cert, key, value)

	await session.commit()
	await session.refresh(cert)
	return OperatorCertification.model_validate(cert)


async def get_expiring_certifications(
	session: AsyncSession,
	days: int = 30,
) -> Sequence[OperatorCertification]:
	"""Get certifications expiring within specified days."""
	cutoff = datetime.utcnow() + timedelta(days=days)
	stmt = select(OperatorCertificationModel).where(
		and_(
			OperatorCertificationModel.expiry_date <= cutoff,
			OperatorCertificationModel.expiry_date >= datetime.utcnow(),
			OperatorCertificationModel.is_active == True,
		)
	).order_by(OperatorCertificationModel.expiry_date)
	result = await session.execute(stmt)
	return [OperatorCertification.model_validate(row) for row in result.scalars().all()]


# =====================================================
# Capacity Planning Service
# =====================================================


async def create_capacity_plan(
	session: AsyncSession,
	project_id: str,
	data: CapacityPlanCreate,
	user_id: str | None = None,
) -> CapacityPlan:
	"""Create a capacity plan for a project."""
	# Get project data
	project_stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.id == project_id
	)
	project_result = await session.execute(project_stmt)
	project = project_result.scalar_one()

	# Calculate capacity needs
	pages_remaining = project.total_estimated_pages - project.scanned_pages
	target_date = data.target_completion_date
	now = datetime.utcnow()
	working_days = max(1, (target_date - now).days)  # Simplified, not accounting for weekends

	required_per_day = pages_remaining / working_days if working_days > 0 else pages_remaining

	# Estimate current capacity (from recent performance)
	seven_days_ago = now - timedelta(days=7)
	session_stmt = select(func.sum(ScanningSesssionModel.pages_scanned)).where(
		and_(
			ScanningSesssionModel.project_id == project_id,
			ScanningSesssionModel.ended_at >= seven_days_ago,
		)
	)
	session_result = await session.execute(session_stmt)
	recent_pages = session_result.scalar() or 0
	current_daily_capacity = recent_pages / 7 if recent_pages > 0 else project.daily_page_target

	capacity_gap = int(required_per_day - current_daily_capacity)

	# Calculate recommended resources (assume 500 pages/operator/day)
	pages_per_operator = 500
	recommended_operators = max(1, int(required_per_day / pages_per_operator) + 1)
	recommended_scanners = max(1, recommended_operators // 2)  # 2 operators per scanner
	recommended_shifts = 1
	if required_per_day > pages_per_operator * 8:  # More than 8 operators
		recommended_shifts = 2
	if required_per_day > pages_per_operator * 16:
		recommended_shifts = 3

	plan = CapacityPlanModel(
		id=uuid7str(),
		project_id=project_id,
		plan_name=data.plan_name,
		target_completion_date=data.target_completion_date,
		assumptions=data.assumptions,
		total_pages_remaining=pages_remaining,
		working_days_remaining=working_days,
		required_pages_per_day=int(required_per_day),
		current_daily_capacity=int(current_daily_capacity),
		capacity_gap=capacity_gap,
		recommended_operators=recommended_operators,
		recommended_scanners=recommended_scanners,
		recommended_shifts_per_day=recommended_shifts,
		created_by_id=user_id,
	)
	session.add(plan)
	await session.commit()
	await session.refresh(plan)
	logger.info(f"Created capacity plan for project {project_id[:8]}...")
	return CapacityPlan.model_validate(plan)


async def get_capacity_plans(
	session: AsyncSession,
	project_id: str,
) -> Sequence[CapacityPlan]:
	"""Get capacity plans for a project."""
	stmt = select(CapacityPlanModel).where(
		CapacityPlanModel.project_id == project_id
	).order_by(CapacityPlanModel.created_at.desc())
	result = await session.execute(stmt)
	return [CapacityPlan.model_validate(row) for row in result.scalars().all()]


# =====================================================
# Document Type Distribution Service
# =====================================================


async def get_document_type_distributions(
	session: AsyncSession,
	project_id: str,
) -> Sequence[DocumentTypeDistribution]:
	"""Get document type distributions for a project."""
	stmt = select(DocumentTypeDistributionModel).where(
		DocumentTypeDistributionModel.project_id == project_id
	).order_by(DocumentTypeDistributionModel.priority.desc())
	result = await session.execute(stmt)
	return [DocumentTypeDistribution.model_validate(row) for row in result.scalars().all()]


async def create_document_type_distribution(
	session: AsyncSession,
	project_id: str,
	data: DocumentTypeDistributionCreate,
) -> DocumentTypeDistribution:
	"""Create a document type distribution entry."""
	dist = DocumentTypeDistributionModel(
		id=uuid7str(),
		project_id=project_id,
		**data.model_dump(),
	)
	session.add(dist)
	await session.commit()
	await session.refresh(dist)
	return DocumentTypeDistribution.model_validate(dist)


async def update_document_type_distribution(
	session: AsyncSession,
	distribution_id: str,
	data: DocumentTypeDistributionUpdate,
) -> DocumentTypeDistribution | None:
	"""Update a document type distribution entry."""
	stmt = select(DocumentTypeDistributionModel).where(
		DocumentTypeDistributionModel.id == distribution_id
	)
	result = await session.execute(stmt)
	dist = result.scalar_one_or_none()
	if not dist:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(dist, key, value)
	dist.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(dist)
	return DocumentTypeDistribution.model_validate(dist)


# =====================================================
# Priority Queue Service
# =====================================================


async def get_priority_queue(
	session: AsyncSession,
	project_id: str | None = None,
	rush_only: bool = False,
) -> Sequence[BatchPriority]:
	"""Get priority queue for batches."""
	stmt = select(BatchPriorityQueueModel)
	if project_id:
		# Get batch IDs for project
		batch_stmt = select(ScanningBatchModel.id).where(
			ScanningBatchModel.project_id == project_id
		)
		batch_result = await session.execute(batch_stmt)
		batch_ids = [r for r in batch_result.scalars().all()]
		stmt = stmt.where(BatchPriorityQueueModel.batch_id.in_(batch_ids))
	if rush_only:
		stmt = stmt.where(BatchPriorityQueueModel.is_rush == True)
	stmt = stmt.order_by(
		BatchPriorityQueueModel.priority.desc(),
		BatchPriorityQueueModel.due_date.asc().nullslast(),
		BatchPriorityQueueModel.created_at.asc(),
	)
	result = await session.execute(stmt)
	return [BatchPriority.model_validate(row) for row in result.scalars().all()]


async def set_batch_priority(
	session: AsyncSession,
	data: BatchPriorityCreate,
) -> BatchPriority:
	"""Set priority for a batch."""
	# Check if priority entry exists
	existing_stmt = select(BatchPriorityQueueModel).where(
		BatchPriorityQueueModel.batch_id == data.batch_id
	)
	existing_result = await session.execute(existing_stmt)
	existing = existing_result.scalar_one_or_none()

	if existing:
		# Update existing
		for key, value in data.model_dump().items():
			setattr(existing, key, value)
		if data.is_rush and data.rush_approved_by_id:
			existing.rush_approved_at = datetime.utcnow()
		existing.updated_at = datetime.utcnow()
		await session.commit()
		await session.refresh(existing)
		return BatchPriority.model_validate(existing)
	else:
		# Create new
		priority_entry = BatchPriorityQueueModel(
			id=uuid7str(),
			**data.model_dump(),
		)
		if data.is_rush and data.rush_approved_by_id:
			priority_entry.rush_approved_at = datetime.utcnow()
		session.add(priority_entry)
		await session.commit()
		await session.refresh(priority_entry)
		return BatchPriority.model_validate(priority_entry)


async def update_batch_priority(
	session: AsyncSession,
	priority_id: str,
	data: BatchPriorityUpdate,
) -> BatchPriority | None:
	"""Update batch priority."""
	stmt = select(BatchPriorityQueueModel).where(BatchPriorityQueueModel.id == priority_id)
	result = await session.execute(stmt)
	priority_entry = result.scalar_one_or_none()
	if not priority_entry:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(priority_entry, key, value)
	priority_entry.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(priority_entry)
	return BatchPriority.model_validate(priority_entry)


# =====================================================
# Contract Service
# =====================================================


async def get_project_contracts(
	session: AsyncSession,
	project_id: str,
) -> Sequence[ProjectContract]:
	"""Get contracts for a project."""
	stmt = select(ProjectContractModel).where(
		ProjectContractModel.project_id == project_id
	).order_by(ProjectContractModel.start_date)
	result = await session.execute(stmt)
	return [ProjectContract.model_validate(row) for row in result.scalars().all()]


async def create_contract(
	session: AsyncSession,
	project_id: str,
	data: ProjectContractCreate,
) -> ProjectContract:
	"""Create a project contract."""
	contract = ProjectContractModel(
		id=uuid7str(),
		project_id=project_id,
		**data.model_dump(),
	)
	session.add(contract)
	await session.commit()
	await session.refresh(contract)
	logger.info(f"Created contract {contract.contract_number}")
	return ProjectContract.model_validate(contract)


async def update_contract(
	session: AsyncSession,
	contract_id: str,
	data: ProjectContractUpdate,
) -> ProjectContract | None:
	"""Update a project contract."""
	stmt = select(ProjectContractModel).where(ProjectContractModel.id == contract_id)
	result = await session.execute(stmt)
	contract = result.scalar_one_or_none()
	if not contract:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(contract, key, value)
	contract.updated_at = datetime.utcnow()

	await session.commit()
	await session.refresh(contract)
	return ProjectContract.model_validate(contract)


# =====================================================
# Workload Forecast Service
# =====================================================


async def create_workload_forecast(
	session: AsyncSession,
	project_id: str,
	forecast_period_start: datetime,
	forecast_period_end: datetime,
) -> WorkloadForecast:
	"""Create a workload forecast based on historical data."""
	# Get historical daily metrics
	metrics_stmt = select(DailyProjectMetricsModel).where(
		DailyProjectMetricsModel.project_id == project_id
	).order_by(DailyProjectMetricsModel.metric_date.desc()).limit(30)
	metrics_result = await session.execute(metrics_stmt)
	metrics = list(metrics_result.scalars().all())

	if not metrics:
		# No historical data, use project targets
		project_stmt = select(ScanningProjectModel).where(
			ScanningProjectModel.id == project_id
		)
		project_result = await session.execute(project_stmt)
		project = project_result.scalar_one()
		daily_avg = project.daily_page_target
	else:
		daily_avg = sum(m.pages_scanned for m in metrics) / len(metrics)

	# Calculate forecast period days
	period_days = max(1, (forecast_period_end - forecast_period_start).days)
	predicted_pages = int(daily_avg * period_days)

	# Estimate resources (assume 500 pages/operator/day)
	pages_per_operator = 500
	predicted_operators = max(1, int(daily_avg / pages_per_operator) + 1)
	predicted_scanners = max(1, predicted_operators // 2)

	forecast = WorkloadForecastModel(
		id=uuid7str(),
		project_id=project_id,
		forecast_period_start=forecast_period_start,
		forecast_period_end=forecast_period_end,
		predicted_pages=predicted_pages,
		predicted_operators_needed=predicted_operators,
		predicted_scanners_needed=predicted_scanners,
		model_used="simple_average",
		confidence_score=0.7 if len(metrics) >= 7 else 0.5,
	)
	session.add(forecast)
	await session.commit()
	await session.refresh(forecast)
	return WorkloadForecast.model_validate(forecast)


async def get_workload_forecasts(
	session: AsyncSession,
	project_id: str,
) -> Sequence[WorkloadForecast]:
	"""Get workload forecasts for a project."""
	stmt = select(WorkloadForecastModel).where(
		WorkloadForecastModel.project_id == project_id
	).order_by(WorkloadForecastModel.forecast_date.desc())
	result = await session.execute(stmt)
	return [WorkloadForecast.model_validate(row) for row in result.scalars().all()]


# =====================================================
# Checkpoint Service
# =====================================================


async def get_project_checkpoints(
	session: AsyncSession,
	project_id: str,
) -> Sequence[ProjectCheckpoint]:
	"""Get checkpoints for a project."""
	stmt = select(ProjectCheckpointModel).where(
		ProjectCheckpointModel.project_id == project_id
	).order_by(ProjectCheckpointModel.checkpoint_number)
	result = await session.execute(stmt)
	return [ProjectCheckpoint.model_validate(row) for row in result.scalars().all()]


async def create_checkpoint(
	session: AsyncSession,
	project_id: str,
	data: ProjectCheckpointCreate,
) -> ProjectCheckpoint:
	"""Create a project checkpoint."""
	checkpoint = ProjectCheckpointModel(
		id=uuid7str(),
		project_id=project_id,
		**data.model_dump(),
	)
	session.add(checkpoint)
	await session.commit()
	await session.refresh(checkpoint)
	logger.info(f"Created checkpoint {checkpoint.name}")
	return ProjectCheckpoint.model_validate(checkpoint)


async def update_checkpoint(
	session: AsyncSession,
	checkpoint_id: str,
	data: ProjectCheckpointUpdate,
	reviewer_id: str | None = None,
	reviewer_name: str | None = None,
) -> ProjectCheckpoint | None:
	"""Update a checkpoint."""
	stmt = select(ProjectCheckpointModel).where(ProjectCheckpointModel.id == checkpoint_id)
	result = await session.execute(stmt)
	checkpoint = result.scalar_one_or_none()
	if not checkpoint:
		return None

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(checkpoint, key, value)

	# If status changed to passed/failed, set review info
	if data.status in (CheckpointStatus.PASSED, CheckpointStatus.FAILED, CheckpointStatus.WAIVED):
		checkpoint.reviewed_at = datetime.utcnow()
		if reviewer_id:
			checkpoint.reviewed_by_id = reviewer_id
		if reviewer_name:
			checkpoint.reviewed_by_name = reviewer_name
		if data.status in (CheckpointStatus.PASSED, CheckpointStatus.WAIVED):
			checkpoint.actual_date = datetime.utcnow()

	await session.commit()
	await session.refresh(checkpoint)
	return ProjectCheckpoint.model_validate(checkpoint)


# =====================================================
# Bulk Operations Service
# =====================================================


async def bulk_import_batches(
	session: AsyncSession,
	project_id: str,
	data: BulkBatchImport,
) -> BulkOperationResult:
	"""Bulk import batches for a project."""
	success_count = 0
	failure_count = 0
	failed_ids: list[str] = []
	errors: list[str] = []

	for i, batch_data in enumerate(data.batches):
		try:
			batch_dict = batch_data.model_dump()
			if data.auto_generate_numbers:
				prefix = data.number_prefix or "B"
				batch_dict["batch_number"] = f"{prefix}{data.starting_number + i:05d}"

			batch = ScanningBatchModel(
				id=uuid7str(),
				project_id=project_id,
				**batch_dict,
			)
			session.add(batch)
			success_count += 1
		except Exception as e:
			failure_count += 1
			failed_ids.append(f"index_{i}")
			errors.append(str(e))

	if success_count > 0:
		await session.commit()
	logger.info(f"Bulk imported {success_count} batches for project {project_id[:8]}...")

	return BulkOperationResult(
		success_count=success_count,
		failure_count=failure_count,
		total_count=len(data.batches),
		failed_ids=failed_ids,
		errors=errors,
	)


async def bulk_update_batches(
	session: AsyncSession,
	data: BulkBatchUpdate,
) -> BulkOperationResult:
	"""Bulk update batches."""
	success_count = 0
	failure_count = 0
	failed_ids: list[str] = []
	errors: list[str] = []

	for batch_id in data.batch_ids:
		try:
			stmt = select(ScanningBatchModel).where(ScanningBatchModel.id == batch_id)
			result = await session.execute(stmt)
			batch = result.scalar_one_or_none()
			if not batch:
				failure_count += 1
				failed_ids.append(batch_id)
				errors.append(f"Batch {batch_id} not found")
				continue

			if data.status:
				batch.status = data.status.value
			if data.assigned_operator_id:
				batch.assigned_operator_id = data.assigned_operator_id
			if data.assigned_scanner_id:
				batch.assigned_scanner_id = data.assigned_scanner_id
			if data.priority:
				batch.priority = data.priority
			batch.updated_at = datetime.utcnow()
			success_count += 1
		except Exception as e:
			failure_count += 1
			failed_ids.append(batch_id)
			errors.append(str(e))

	if success_count > 0:
		await session.commit()
	logger.info(f"Bulk updated {success_count} batches")

	return BulkOperationResult(
		success_count=success_count,
		failure_count=failure_count,
		total_count=len(data.batch_ids),
		failed_ids=failed_ids,
		errors=errors,
	)


# =====================================================
# Dashboard and Analytics Service
# =====================================================


async def get_project_dashboard(
	session: AsyncSession,
	project_id: str,
) -> ProjectDashboard:
	"""Get comprehensive project dashboard data."""
	# Get project
	project_stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.id == project_id
	)
	project_result = await session.execute(project_stmt)
	project = project_result.scalar_one()

	# Get batch counts by status
	batch_stmt = select(
		ScanningBatchModel.status,
		func.count(ScanningBatchModel.id).label("count"),
	).where(
		ScanningBatchModel.project_id == project_id
	).group_by(ScanningBatchModel.status)
	batch_result = await session.execute(batch_stmt)
	batch_counts = {row.status: row.count for row in batch_result}

	# Get today's progress
	today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
	today_stmt = select(func.sum(ScanningSesssionModel.pages_scanned)).where(
		and_(
			ScanningSesssionModel.project_id == project_id,
			ScanningSesssionModel.started_at >= today_start,
		)
	)
	today_result = await session.execute(today_stmt)
	pages_today = today_result.scalar() or 0

	# Count active operators
	active_stmt = select(func.count(ScanningSesssionModel.id)).where(
		and_(
			ScanningSesssionModel.project_id == project_id,
			ScanningSesssionModel.ended_at.is_(None),
		)
	)
	active_result = await session.execute(active_stmt)
	active_operators = active_result.scalar() or 0

	# Get SLA counts
	sla_stmt = select(
		SLAModel.status,
		func.count(SLAModel.id).label("count"),
	).where(
		SLAModel.project_id == project_id
	).group_by(SLAModel.status)
	sla_result = await session.execute(sla_stmt)
	sla_counts = {row.status: row.count for row in sla_result}

	# Get issue counts
	issue_stmt = select(
		ProjectIssueModel.severity,
		func.count(ProjectIssueModel.id).label("count"),
	).where(
		and_(
			ProjectIssueModel.project_id == project_id,
			ProjectIssueModel.status.in_(["open", "in_progress"]),
		)
	).group_by(ProjectIssueModel.severity)
	issue_result = await session.execute(issue_stmt)
	issue_counts = {row.severity: row.count for row in issue_result}

	# Get QC pass rate
	batch_ids_stmt = select(ScanningBatchModel.id).where(
		ScanningBatchModel.project_id == project_id
	)
	batch_ids_result = await session.execute(batch_ids_stmt)
	batch_ids = [r for r in batch_ids_result.scalars().all()]

	qc_pass_rate = 0.0
	avg_quality = 0.0
	pending_qc = 0
	if batch_ids:
		qc_stmt = select(
			func.count(QualityControlSampleModel.id).label("total"),
			func.sum(
				func.case((QualityControlSampleModel.review_status == "passed", 1), else_=0)
			).label("passed"),
			func.avg(QualityControlSampleModel.image_quality).label("avg_quality"),
		).where(QualityControlSampleModel.batch_id.in_(batch_ids))
		qc_result = await session.execute(qc_stmt)
		qc_row = qc_result.one()
		if qc_row.total and qc_row.total > 0:
			qc_pass_rate = (qc_row.passed or 0) / qc_row.total * 100
			avg_quality = float(qc_row.avg_quality or 0)

		pending_stmt = select(func.count(QualityControlSampleModel.id)).where(
			and_(
				QualityControlSampleModel.batch_id.in_(batch_ids),
				QualityControlSampleModel.review_status == "pending",
			)
		)
		pending_result = await session.execute(pending_stmt)
		pending_qc = pending_result.scalar() or 0

	# Get budget info
	budget_stmt = select(ProjectBudgetModel).where(
		ProjectBudgetModel.project_id == project_id
	)
	budget_result = await session.execute(budget_stmt)
	budget = budget_result.scalar_one_or_none()

	# Calculate completion
	completion_pct = 0.0
	if project.total_estimated_pages > 0:
		completion_pct = project.scanned_pages / project.total_estimated_pages * 100

	# Calculate schedule
	days_remaining = None
	on_schedule = True
	projected_completion = None
	if project.target_date:
		days_remaining = (project.target_date - datetime.utcnow()).days
		if days_remaining < 0:
			on_schedule = False

	# Calculate projected completion based on velocity
	if project.scanned_pages > 0 and project.start_date:
		days_active = max(1, (datetime.utcnow() - project.start_date).days)
		velocity = project.scanned_pages / days_active
		if velocity > 0:
			remaining = project.total_estimated_pages - project.scanned_pages
			days_to_complete = remaining / velocity
			projected_completion = datetime.utcnow() + timedelta(days=days_to_complete)
			if project.target_date and projected_completion > project.target_date:
				on_schedule = False

	return ProjectDashboard(
		project_id=project_id,
		project_name=project.name,
		status=ScanningProjectStatus(project.status),
		total_estimated_pages=project.total_estimated_pages,
		scanned_pages=project.scanned_pages,
		verified_pages=project.verified_pages,
		rejected_pages=project.rejected_pages,
		completion_percentage=round(completion_pct, 1),
		pages_scanned_today=pages_today,
		pages_target_today=project.daily_page_target,
		target_variance=pages_today - project.daily_page_target,
		active_operators=active_operators,
		active_scanners=active_operators,  # Simplified
		batches_pending=batch_counts.get("pending", 0),
		batches_in_progress=batch_counts.get("scanning", 0) + batch_counts.get("ocr_processing", 0),
		batches_completed=batch_counts.get("completed", 0),
		batches_in_qc=batch_counts.get("qc_pending", 0),
		qc_pass_rate=round(qc_pass_rate, 1),
		avg_quality_score=round(avg_quality, 1),
		pending_qc_reviews=pending_qc,
		sla_on_track=sla_counts.get("on_track", 0),
		sla_at_risk=sla_counts.get("at_risk", 0),
		sla_breached=sla_counts.get("breached", 0),
		critical_issues=issue_counts.get("critical", 0),
		high_issues=issue_counts.get("major", 0),
		open_issues_total=sum(issue_counts.values()),
		days_remaining=days_remaining,
		projected_completion_date=projected_completion,
		on_schedule=on_schedule,
		budget_spent=budget.spent_to_date if budget else 0.0,
		budget_remaining=(budget.total_budget - budget.spent_to_date) if budget else 0.0,
		cost_per_page=round(budget.spent_to_date / project.scanned_pages, 4) if budget and project.scanned_pages > 0 else 0.0,
	)


async def get_burndown_chart(
	session: AsyncSession,
	project_id: str,
) -> BurndownChart:
	"""Get burndown chart data for a project."""
	# Get project
	project_stmt = select(ScanningProjectModel).where(
		ScanningProjectModel.id == project_id
	)
	project_result = await session.execute(project_stmt)
	project = project_result.scalar_one()

	start_date = project.start_date or project.created_at
	target_date = project.target_date or (datetime.utcnow() + timedelta(days=90))
	total_pages = project.total_estimated_pages

	# Get daily metrics for data points
	metrics_stmt = select(DailyProjectMetricsModel).where(
		DailyProjectMetricsModel.project_id == project_id
	).order_by(DailyProjectMetricsModel.metric_date)
	metrics_result = await session.execute(metrics_stmt)
	metrics = list(metrics_result.scalars().all())

	# Build data points
	data_points: list[BurndownDataPoint] = []
	total_days = max(1, (target_date - start_date).days)
	ideal_daily_burn = total_pages / total_days

	cumulative_scanned = 0
	for metric in metrics:
		cumulative_scanned += metric.pages_scanned
		pages_remaining = total_pages - cumulative_scanned
		days_elapsed = (metric.metric_date - start_date).days
		ideal_remaining = max(0, total_pages - (ideal_daily_burn * days_elapsed))

		data_points.append(BurndownDataPoint(
			date=metric.metric_date,
			pages_remaining=max(0, pages_remaining),
			ideal_remaining=int(ideal_remaining),
			velocity=metric.pages_scanned,
		))

	# Add current state if no metrics for today
	if not data_points or data_points[-1].date.date() != datetime.utcnow().date():
		pages_remaining = total_pages - project.scanned_pages
		days_elapsed = (datetime.utcnow() - start_date).days
		ideal_remaining = max(0, total_pages - (ideal_daily_burn * days_elapsed))
		data_points.append(BurndownDataPoint(
			date=datetime.utcnow(),
			pages_remaining=pages_remaining,
			ideal_remaining=int(ideal_remaining),
			velocity=0,
		))

	# Calculate projected completion
	projected_completion = None
	is_on_track = True
	if data_points and len(data_points) >= 2:
		recent_velocity = sum(dp.velocity for dp in data_points[-7:]) / min(7, len(data_points))
		if recent_velocity > 0:
			remaining = data_points[-1].pages_remaining
			days_to_complete = remaining / recent_velocity
			projected_completion = datetime.utcnow() + timedelta(days=days_to_complete)
			is_on_track = projected_completion <= target_date

	return BurndownChart(
		project_id=project_id,
		start_date=start_date,
		target_end_date=target_date,
		total_pages=total_pages,
		data_points=data_points,
		projected_completion_date=projected_completion,
		is_on_track=is_on_track,
	)


async def get_velocity_chart(
	session: AsyncSession,
	project_id: str,
	period_days: int = 30,
) -> VelocityChart:
	"""Get velocity chart data for a project."""
	period_end = datetime.utcnow()
	period_start = period_end - timedelta(days=period_days)

	# Get daily metrics
	metrics_stmt = select(DailyProjectMetricsModel).where(
		and_(
			DailyProjectMetricsModel.project_id == project_id,
			DailyProjectMetricsModel.metric_date >= period_start,
			DailyProjectMetricsModel.metric_date <= period_end,
		)
	).order_by(DailyProjectMetricsModel.metric_date)
	metrics_result = await session.execute(metrics_stmt)
	metrics = list(metrics_result.scalars().all())

	data_points: list[VelocityDataPoint] = []
	for metric in metrics:
		pages_per_op = metric.pages_scanned / metric.operator_count if metric.operator_count > 0 else 0
		data_points.append(VelocityDataPoint(
			date=metric.metric_date,
			pages_scanned=metric.pages_scanned,
			operators_active=metric.operator_count,
			pages_per_operator=round(pages_per_op, 1),
		))

	# Calculate average and trend
	avg_velocity = 0.0
	velocity_trend = 0.0
	if data_points:
		avg_velocity = sum(dp.pages_scanned for dp in data_points) / len(data_points)

		# Simple trend: compare last week to previous week
		if len(data_points) >= 14:
			last_week = sum(dp.pages_scanned for dp in data_points[-7:])
			prev_week = sum(dp.pages_scanned for dp in data_points[-14:-7])
			if prev_week > 0:
				velocity_trend = (last_week - prev_week) / prev_week * 100

	return VelocityChart(
		project_id=project_id,
		period_start=period_start,
		period_end=period_end,
		data_points=data_points,
		average_velocity=round(avg_velocity, 1),
		velocity_trend=round(velocity_trend, 1),
	)


async def get_multi_location_dashboard(
	session: AsyncSession,
	project_id: str,
	tenant_id: str,
) -> MultiLocationDashboard:
	"""Get multi-location dashboard for a project."""
	# Get all locations for tenant
	locations_stmt = select(ScanningLocationModel).where(
		and_(
			ScanningLocationModel.tenant_id == tenant_id,
			ScanningLocationModel.is_active == True,
		)
	)
	locations_result = await session.execute(locations_stmt)
	locations = list(locations_result.scalars().all())

	location_metrics: list[LocationMetrics] = []
	total_capacity = 0
	utilized_capacity = 0

	for location in locations:
		total_capacity += location.daily_page_capacity

		# Get pages scanned today at this location
		today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

		# Get sub-projects for this location
		sub_stmt = select(SubProjectModel.id).where(
			and_(
				SubProjectModel.parent_project_id == project_id,
				SubProjectModel.assigned_location_id == location.id,
			)
		)
		sub_result = await session.execute(sub_stmt)
		sub_ids = [r for r in sub_result.scalars().all()]

		pages_today = 0
		total_pages = 0
		active_ops = 0

		# For now, simplified - would need to track sessions by location
		# This would require adding location_id to scanning sessions

		utilization = 0.0
		if location.daily_page_capacity > 0:
			utilization = pages_today / location.daily_page_capacity * 100
			utilized_capacity += min(pages_today, location.daily_page_capacity)

		location_metrics.append(LocationMetrics(
			location_id=location.id,
			location_name=location.name,
			total_pages_scanned=total_pages,
			pages_today=pages_today,
			active_operators=active_ops,
			active_scanners=0,
			capacity_utilization=round(utilization, 1),
			avg_quality_score=0.0,
			avg_pages_per_hour=0.0,
		))

	overall_utilization = (utilized_capacity / total_capacity * 100) if total_capacity > 0 else 0.0

	return MultiLocationDashboard(
		project_id=project_id,
		locations=location_metrics,
		total_active_locations=len(locations),
		total_capacity=total_capacity,
		utilized_capacity=utilized_capacity,
		overall_utilization=round(overall_utilization, 1),
	)

# =====================================================
# Gamification Service
# =====================================================


async def get_leaderboard(
	session: AsyncSession,
	tenant_id: str,
	limit: int = 10,
) -> Sequence[OperatorDailyMetrics]:
	"""Get the daily leaderboard."""
	today = date.today()
	stmt = select(OperatorDailyMetricsModel).where(
		and_(
			OperatorDailyMetricsModel.metric_date >= datetime.combine(today, datetime.min.time()),
			OperatorDailyMetricsModel.metric_date <= datetime.combine(today, datetime.max.time()),
		)
	).order_by(OperatorDailyMetricsModel.pages_scanned.desc()).limit(limit)
	
	result = await session.execute(stmt)
	return [OperatorDailyMetrics.model_validate(row) for row in result.scalars().all()]


async def get_hourly_performance(
	session: AsyncSession,
	operator_id: str,
) -> list[dict]:
	"""Get hourly performance for the current operator."""
	today = date.today()
	# We'll query scanning sessions for today
	stmt = select(ScanningSesssionModel).where(
		and_(
			ScanningSesssionModel.operator_id == str(operator_id),
			ScanningSesssionModel.started_at >= datetime.combine(today, datetime.min.time()),
		)
	)
	result = await session.execute(stmt)
	sessions = result.scalars().all()

	# Aggregate by hour
	hourly_data = {}
	for session in sessions:
		hour = session.started_at.strftime("%H:00")
		if hour not in hourly_data:
			hourly_data[hour] = 0
		hourly_data[hour] += session.pages_scanned

	# Format for chart
	chart_data = [
		{"name": hour, "pages": pages}
		for hour, pages in sorted(hourly_data.items())
	]
	
	# If no data, return empty list or some defaults? 
	# Let's return what we have.
	return chart_data
