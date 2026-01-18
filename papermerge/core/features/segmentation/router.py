# (c) Copyright Datacraft, 2026
"""API endpoints for document segmentation."""
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from celery.app import default_app as celery_app

from papermerge.core.db.engine import get_session
from papermerge.core.features.auth import get_current_user
from papermerge.core.features.users.db.orm import User

from .db.orm import (
	ScanSegment,
	SegmentationJob,
	SegmentationMethod as DBSegmentationMethod,
	SegmentStatus as DBSegmentStatus,
)
from .schema import (
	SegmentationRequest,
	SegmentSchema,
	SegmentListResponse,
	SegmentationJobSchema,
	SegmentationJobResponse,
	SegmentUpdateRequest,
	SegmentVerifyRequest,
	SegmentCreateDocumentRequest,
	SegmentMergeRequest,
	SegmentSplitRequest,
	SegmentationStatsSchema,
	SegmentationMethodEnum,
	SegmentStatusEnum,
	BoundarySchema,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/segmentation", tags=["Segmentation"])


# Constants
SEGMENT_DOCUMENT_TASK = "ocrworker.segmentation_tasks.segment_document"


@router.post(
	"/analyze",
	response_model=SegmentationJobResponse,
	status_code=status.HTTP_202_ACCEPTED,
	summary="Start document segmentation",
	description="Analyze a document scan for multiple documents and segment them.",
)
async def start_segmentation(
	request: SegmentationRequest,
	db: Annotated[AsyncSession, Depends(get_session)],
	user: Annotated[User, Depends(get_current_user)],
) -> SegmentationJobResponse:
	"""Start an async segmentation job."""
	# Create job record
	job = SegmentationJob(
		source_document_id=request.document_id,
		source_page_number=request.page_number,
		method=DBSegmentationMethod(request.method.value),
		auto_create_documents=request.auto_create_documents,
		min_confidence_threshold=request.min_confidence,
		status="pending",
		initiated_by_id=user.id,
		tenant_id=user.tenant_id,
	)
	db.add(job)
	await db.commit()
	await db.refresh(job)

	# Start async Celery task
	try:
		task = celery_app.send_task(
			SEGMENT_DOCUMENT_TASK,
			kwargs={
				"job_id": job.id,
				"document_id": request.document_id,
				"page_number": request.page_number,
				"method": request.method.value,
				"min_confidence": request.min_confidence,
				"deskew": request.deskew,
				"auto_create_documents": request.auto_create_documents,
			},
		)
		job.celery_task_id = task.id
		job.status = "processing"
		job.started_at = datetime.utcnow()
		await db.commit()

		return SegmentationJobResponse(
			job_id=job.id,
			celery_task_id=task.id,
			status="processing",
			message="Segmentation job started",
		)

	except Exception as e:
		logger.error(f"Failed to start segmentation task: {e}")
		job.status = "failed"
		job.error_message = str(e)
		await db.commit()

		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail=f"Failed to start segmentation: {e}",
		)


@router.get(
	"/jobs/{job_id}",
	response_model=SegmentationJobSchema,
	summary="Get segmentation job status",
)
async def get_job(
	job_id: str,
	db: Annotated[AsyncSession, Depends(get_session)],
	user: Annotated[User, Depends(get_current_user)],
) -> SegmentationJobSchema:
	"""Get status of a segmentation job."""
	stmt = select(SegmentationJob).where(
		SegmentationJob.id == job_id,
		SegmentationJob.tenant_id == user.tenant_id,
	)
	result = await db.execute(stmt)
	job = result.scalar_one_or_none()

	if not job:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Segmentation job not found",
		)

	return SegmentationJobSchema.model_validate(job)


@router.get(
	"/segments",
	response_model=SegmentListResponse,
	summary="List segments",
	description="List all segments, optionally filtered by document or status.",
)
async def list_segments(
	db: Annotated[AsyncSession, Depends(get_session)],
	user: Annotated[User, Depends(get_current_user)],
	document_id: str | None = Query(None, description="Filter by original document"),
	status_filter: SegmentStatusEnum | None = Query(None, alias="status"),
	needs_review: bool | None = Query(None, description="Filter segments needing review"),
	page: int = Query(1, ge=1),
	page_size: int = Query(50, ge=1, le=200),
) -> SegmentListResponse:
	"""List segments with optional filters."""
	# Base query
	stmt = select(ScanSegment).where(
		ScanSegment.tenant_id == user.tenant_id
	)

	# Apply filters
	if document_id:
		stmt = stmt.where(ScanSegment.original_scan_id == document_id)

	if status_filter:
		stmt = stmt.where(
			ScanSegment.status == DBSegmentStatus(status_filter.value)
		)

	if needs_review is not None:
		if needs_review:
			stmt = stmt.where(
				and_(
					ScanSegment.manually_verified == False,
					ScanSegment.segmentation_confidence < 0.7,
				)
			)
		else:
			stmt = stmt.where(ScanSegment.manually_verified == True)

	# Count total
	count_stmt = select(func.count()).select_from(stmt.subquery())
	total = (await db.execute(count_stmt)).scalar() or 0

	# Paginate
	stmt = stmt.offset((page - 1) * page_size).limit(page_size)
	stmt = stmt.order_by(ScanSegment.created_at.desc())

	result = await db.execute(stmt)
	segments = result.scalars().all()

	return SegmentListResponse(
		items=[_segment_to_schema(s) for s in segments],
		total=total,
		page=page,
		page_size=page_size,
	)


@router.get(
	"/segments/{segment_id}",
	response_model=SegmentSchema,
	summary="Get segment details",
)
async def get_segment(
	segment_id: str,
	db: Annotated[AsyncSession, Depends(get_session)],
	user: Annotated[User, Depends(get_current_user)],
) -> SegmentSchema:
	"""Get details of a specific segment."""
	stmt = select(ScanSegment).where(
		ScanSegment.id == segment_id,
		ScanSegment.tenant_id == user.tenant_id,
	)
	result = await db.execute(stmt)
	segment = result.scalar_one_or_none()

	if not segment:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Segment not found",
		)

	return _segment_to_schema(segment)


@router.patch(
	"/segments/{segment_id}",
	response_model=SegmentSchema,
	summary="Update segment",
)
async def update_segment(
	segment_id: str,
	request: SegmentUpdateRequest,
	db: Annotated[AsyncSession, Depends(get_session)],
	user: Annotated[User, Depends(get_current_user)],
) -> SegmentSchema:
	"""Update segment properties."""
	stmt = select(ScanSegment).where(
		ScanSegment.id == segment_id,
		ScanSegment.tenant_id == user.tenant_id,
	)
	result = await db.execute(stmt)
	segment = result.scalar_one_or_none()

	if not segment:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Segment not found",
		)

	# Apply updates
	if request.status is not None:
		segment.status = DBSegmentStatus(request.status.value)

	if request.boundary is not None:
		segment.boundary_x = request.boundary.x
		segment.boundary_y = request.boundary.y
		segment.boundary_width = request.boundary.width
		segment.boundary_height = request.boundary.height

	if request.document_type_hint is not None:
		segment.document_type_hint = request.document_type_hint

	if request.notes is not None:
		segment.notes = request.notes

	segment.updated_at = datetime.utcnow()
	await db.commit()
	await db.refresh(segment)

	return _segment_to_schema(segment)


@router.post(
	"/segments/{segment_id}/verify",
	response_model=SegmentSchema,
	summary="Verify segment",
)
async def verify_segment(
	segment_id: str,
	request: SegmentVerifyRequest,
	db: Annotated[AsyncSession, Depends(get_session)],
	user: Annotated[User, Depends(get_current_user)],
) -> SegmentSchema:
	"""Verify/approve a segment after review."""
	stmt = select(ScanSegment).where(
		ScanSegment.id == segment_id,
		ScanSegment.tenant_id == user.tenant_id,
	)
	result = await db.execute(stmt)
	segment = result.scalar_one_or_none()

	if not segment:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Segment not found",
		)

	segment.manually_verified = True
	segment.verified_by_id = user.id
	segment.verified_at = datetime.utcnow()
	segment.status = DBSegmentStatus.APPROVED if request.approved else DBSegmentStatus.REJECTED

	if request.notes:
		segment.notes = request.notes

	segment.updated_at = datetime.utcnow()
	await db.commit()
	await db.refresh(segment)

	return _segment_to_schema(segment)


@router.post(
	"/segments/{segment_id}/create-document",
	status_code=status.HTTP_201_CREATED,
	summary="Create document from segment",
	description="Convert an approved segment into a standalone document.",
)
async def create_document_from_segment(
	segment_id: str,
	request: SegmentCreateDocumentRequest,
	db: Annotated[AsyncSession, Depends(get_session)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Create a document from an approved segment."""
	stmt = select(ScanSegment).where(
		ScanSegment.id == segment_id,
		ScanSegment.tenant_id == user.tenant_id,
	)
	result = await db.execute(stmt)
	segment = result.scalar_one_or_none()

	if not segment:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Segment not found",
		)

	if segment.document_id:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="Document already created for this segment",
		)

	if segment.status == DBSegmentStatus.REJECTED:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="Cannot create document from rejected segment",
		)

	# TODO: Implement document creation from segment file
	# This would involve:
	# 1. Loading segment image from segment_file_path
	# 2. Creating new document in destination folder
	# 3. Linking segment to document
	# 4. Triggering OCR on the new document

	raise HTTPException(
		status_code=status.HTTP_501_NOT_IMPLEMENTED,
		detail="Document creation from segment not yet implemented",
	)


@router.delete(
	"/segments/{segment_id}",
	status_code=status.HTTP_204_NO_CONTENT,
	summary="Delete segment",
)
async def delete_segment(
	segment_id: str,
	db: Annotated[AsyncSession, Depends(get_session)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Delete a segment."""
	stmt = select(ScanSegment).where(
		ScanSegment.id == segment_id,
		ScanSegment.tenant_id == user.tenant_id,
	)
	result = await db.execute(stmt)
	segment = result.scalar_one_or_none()

	if not segment:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Segment not found",
		)

	if segment.document_id:
		raise HTTPException(
			status_code=status.HTTP_400_BAD_REQUEST,
			detail="Cannot delete segment with linked document",
		)

	await db.delete(segment)
	await db.commit()


@router.get(
	"/stats",
	response_model=SegmentationStatsSchema,
	summary="Get segmentation statistics",
)
async def get_stats(
	db: Annotated[AsyncSession, Depends(get_session)],
	user: Annotated[User, Depends(get_current_user)],
) -> SegmentationStatsSchema:
	"""Get segmentation statistics for the tenant."""
	base_filter = ScanSegment.tenant_id == user.tenant_id

	# Total segments
	total = (await db.execute(
		select(func.count()).where(base_filter)
	)).scalar() or 0

	# Pending review
	pending = (await db.execute(
		select(func.count()).where(
			base_filter,
			ScanSegment.status == DBSegmentStatus.PENDING,
		)
	)).scalar() or 0

	# Approved
	approved = (await db.execute(
		select(func.count()).where(
			base_filter,
			ScanSegment.status == DBSegmentStatus.APPROVED,
		)
	)).scalar() or 0

	# Rejected
	rejected = (await db.execute(
		select(func.count()).where(
			base_filter,
			ScanSegment.status == DBSegmentStatus.REJECTED,
		)
	)).scalar() or 0

	# Average confidence
	avg_conf = (await db.execute(
		select(func.avg(ScanSegment.segmentation_confidence)).where(base_filter)
	)).scalar() or 0.0

	# Documents created
	docs_created = (await db.execute(
		select(func.count()).where(
			base_filter,
			ScanSegment.document_id.isnot(None),
		)
	)).scalar() or 0

	# Multi-document scans (distinct original scans with > 1 segment)
	multi_doc_subq = (
		select(ScanSegment.original_scan_id)
		.where(base_filter)
		.group_by(ScanSegment.original_scan_id)
		.having(func.max(ScanSegment.total_segments) > 1)
	)
	multi_doc = (await db.execute(
		select(func.count()).select_from(multi_doc_subq.subquery())
	)).scalar() or 0

	return SegmentationStatsSchema(
		total_segments=total,
		pending_review=pending,
		approved=approved,
		rejected=rejected,
		avg_confidence=round(avg_conf, 3),
		documents_created=docs_created,
		multi_document_scans=multi_doc,
	)


def _segment_to_schema(segment: ScanSegment) -> SegmentSchema:
	"""Convert ORM model to schema."""
	boundary = None
	if segment.boundary_x is not None:
		boundary = BoundarySchema(
			x=segment.boundary_x,
			y=segment.boundary_y,
			width=segment.boundary_width,
			height=segment.boundary_height,
		)

	return SegmentSchema(
		id=segment.id,
		original_scan_id=segment.original_scan_id,
		original_page_number=segment.original_page_number,
		document_id=segment.document_id,
		segment_number=segment.segment_number,
		total_segments=segment.total_segments,
		boundary=boundary,
		rotation_angle=segment.rotation_angle,
		was_deskewed=segment.was_deskewed,
		segmentation_confidence=segment.segmentation_confidence,
		segmentation_method=SegmentationMethodEnum(segment.segmentation_method.value),
		status=SegmentStatusEnum(segment.status.value),
		manually_verified=segment.manually_verified,
		verified_by_id=segment.verified_by_id,
		verified_at=segment.verified_at,
		document_type_hint=segment.document_type_hint,
		segment_width=segment.segment_width,
		segment_height=segment.segment_height,
		needs_review=segment.needs_review,
		created_at=segment.created_at,
		updated_at=segment.updated_at,
	)
