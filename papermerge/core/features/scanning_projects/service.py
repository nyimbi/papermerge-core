# (c) Copyright Datacraft, 2026
"""Service layer for Scanning Projects feature."""
import logging
from datetime import datetime, timedelta
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
