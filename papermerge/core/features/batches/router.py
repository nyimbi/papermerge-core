# (c) Copyright Datacraft, 2026
"""
API router for batch management.
"""
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7str

from papermerge.core.db.engine import get_db
from papermerge.core.auth import get_current_user
from papermerge.core.features.users.db.orm import User

from .db.orm import ScanBatch, SourceLocation, BatchStatus, LocationType
from .schema import (
	SourceLocationCreate,
	SourceLocationUpdate,
	SourceLocation as SourceLocationSchema,
	SourceLocationTree,
	ScanBatchCreate,
	ScanBatchUpdate,
	ScanBatch as ScanBatchSchema,
	ScanBatchSummary,
	ScanBatchWithLocation,
	BatchDashboardStats,
)

router = APIRouter(prefix="/batches", tags=["batches"])
location_router = APIRouter(prefix="/locations", tags=["locations"])


# ============ Source Locations ============

@location_router.get("", response_model=list[SourceLocationSchema])
async def list_locations(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	location_type: LocationType | None = None,
	parent_id: str | None = None,
	active_only: bool = True,
	skip: int = 0,
	limit: int = 100,
):
	"""List source locations with optional filtering."""
	query = select(SourceLocation)

	if location_type:
		query = query.where(SourceLocation.location_type == location_type)
	if parent_id:
		query = query.where(SourceLocation.parent_id == parent_id)
	elif parent_id is None:
		# Top-level only if no parent specified
		query = query.where(SourceLocation.parent_id.is_(None))
	if active_only:
		query = query.where(SourceLocation.is_active == True)

	query = query.offset(skip).limit(limit)
	result = await db.execute(query)
	return result.scalars().all()


@location_router.get("/tree", response_model=list[SourceLocationTree])
async def get_location_tree(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	active_only: bool = True,
):
	"""Get hierarchical tree of all locations."""
	query = select(SourceLocation)
	if active_only:
		query = query.where(SourceLocation.is_active == True)

	result = await db.execute(query)
	all_locations = result.scalars().all()

	# Build tree
	location_map = {loc.id: loc for loc in all_locations}
	roots = []

	for loc in all_locations:
		if loc.parent_id is None:
			roots.append(loc)

	def build_tree(location) -> SourceLocationTree:
		children = [
			build_tree(location_map[child.id])
			for child in all_locations
			if child.parent_id == location.id
		]
		return SourceLocationTree(
			**SourceLocationSchema.model_validate(location).model_dump(),
			children=children,
		)

	return [build_tree(root) for root in roots]


@location_router.post("", response_model=SourceLocationSchema, status_code=status.HTTP_201_CREATED)
async def create_location(
	data: SourceLocationCreate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Create a new source location."""
	location = SourceLocation(
		id=uuid7str(),
		**data.model_dump(),
	)
	db.add(location)
	await db.commit()
	await db.refresh(location)
	return location


@location_router.get("/{location_id}", response_model=SourceLocationSchema)
async def get_location(
	location_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get a specific source location."""
	result = await db.execute(
		select(SourceLocation).where(SourceLocation.id == location_id)
	)
	location = result.scalar_one_or_none()
	if not location:
		raise HTTPException(status_code=404, detail="Location not found")
	return location


@location_router.patch("/{location_id}", response_model=SourceLocationSchema)
async def update_location(
	location_id: str,
	data: SourceLocationUpdate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Update a source location."""
	result = await db.execute(
		select(SourceLocation).where(SourceLocation.id == location_id)
	)
	location = result.scalar_one_or_none()
	if not location:
		raise HTTPException(status_code=404, detail="Location not found")

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(location, key, value)

	location.updated_at = datetime.utcnow()
	await db.commit()
	await db.refresh(location)
	return location


@location_router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(
	location_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Delete a source location."""
	result = await db.execute(
		select(SourceLocation).where(SourceLocation.id == location_id)
	)
	location = result.scalar_one_or_none()
	if not location:
		raise HTTPException(status_code=404, detail="Location not found")

	await db.delete(location)
	await db.commit()


# ============ Scan Batches ============

def _generate_batch_number() -> str:
	"""Generate unique batch number."""
	now = datetime.utcnow()
	return f"BATCH-{now.year}-{uuid7str()[:8].upper()}"


@router.get("", response_model=list[ScanBatchSummary])
async def list_batches(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
	status_filter: BatchStatus | None = Query(None, alias="status"),
	project_id: str | None = None,
	operator_id: UUID | None = None,
	skip: int = 0,
	limit: int = 50,
):
	"""List scan batches with optional filtering."""
	query = select(ScanBatch)

	if status_filter:
		query = query.where(ScanBatch.status == status_filter)
	if project_id:
		query = query.where(ScanBatch.project_id == project_id)
	if operator_id:
		query = query.where(ScanBatch.operator_id == operator_id)

	query = query.order_by(ScanBatch.created_at.desc())
	query = query.offset(skip).limit(limit)

	result = await db.execute(query)
	return result.scalars().all()


@router.get("/stats", response_model=BatchDashboardStats)
async def get_batch_stats(
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get batch dashboard statistics."""
	# Total batches
	total_result = await db.execute(select(func.count(ScanBatch.id)))
	total_batches = total_result.scalar() or 0

	# Active batches
	active_result = await db.execute(
		select(func.count(ScanBatch.id))
		.where(ScanBatch.status.in_([BatchStatus.CREATED, BatchStatus.IN_PROGRESS, BatchStatus.PAUSED]))
	)
	active_batches = active_result.scalar() or 0

	# Completed batches
	completed_result = await db.execute(
		select(func.count(ScanBatch.id))
		.where(ScanBatch.status == BatchStatus.COMPLETED)
	)
	completed_batches = completed_result.scalar() or 0

	# Document/page totals
	totals_result = await db.execute(
		select(
			func.sum(ScanBatch.total_documents),
			func.sum(ScanBatch.total_pages),
			func.sum(ScanBatch.documents_requiring_rescan),
			func.avg(ScanBatch.average_quality_score),
		)
	)
	totals = totals_result.one()

	# Batches by status
	status_result = await db.execute(
		select(ScanBatch.status, func.count(ScanBatch.id))
		.group_by(ScanBatch.status)
	)
	batches_by_status = {str(row[0].value): row[1] for row in status_result}

	# Recent batches
	recent_result = await db.execute(
		select(ScanBatch)
		.order_by(ScanBatch.created_at.desc())
		.limit(10)
	)
	recent_batches = recent_result.scalars().all()

	return BatchDashboardStats(
		total_batches=total_batches,
		active_batches=active_batches,
		completed_batches=completed_batches,
		total_documents_scanned=totals[0] or 0,
		total_pages_scanned=totals[1] or 0,
		documents_requiring_rescan=totals[2] or 0,
		average_quality_score=float(totals[3]) if totals[3] else None,
		batches_by_status=batches_by_status,
		recent_batches=[
			ScanBatchSummary.model_validate(b) for b in recent_batches
		],
	)


@router.post("", response_model=ScanBatchSchema, status_code=status.HTTP_201_CREATED)
async def create_batch(
	data: ScanBatchCreate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Create a new scan batch."""
	batch = ScanBatch(
		id=uuid7str(),
		batch_number=data.batch_number or _generate_batch_number(),
		operator_id=user.id,
		**data.model_dump(exclude={"batch_number"}),
	)
	db.add(batch)
	await db.commit()
	await db.refresh(batch)
	return batch


@router.get("/{batch_id}", response_model=ScanBatchWithLocation)
async def get_batch(
	batch_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Get a specific scan batch."""
	result = await db.execute(
		select(ScanBatch).where(ScanBatch.id == batch_id)
	)
	batch = result.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")
	return batch


@router.patch("/{batch_id}", response_model=ScanBatchSchema)
async def update_batch(
	batch_id: str,
	data: ScanBatchUpdate,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Update a scan batch."""
	result = await db.execute(
		select(ScanBatch).where(ScanBatch.id == batch_id)
	)
	batch = result.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	update_data = data.model_dump(exclude_unset=True)
	for key, value in update_data.items():
		setattr(batch, key, value)

	# Update timestamps based on status
	if data.status == BatchStatus.IN_PROGRESS and not batch.started_at:
		batch.started_at = datetime.utcnow()
	elif data.status in [BatchStatus.COMPLETED, BatchStatus.APPROVED]:
		batch.completed_at = datetime.utcnow()

	batch.updated_at = datetime.utcnow()
	await db.commit()
	await db.refresh(batch)
	return batch


@router.post("/{batch_id}/start", response_model=ScanBatchSchema)
async def start_batch(
	batch_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Start scanning for a batch."""
	result = await db.execute(
		select(ScanBatch).where(ScanBatch.id == batch_id)
	)
	batch = result.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	if batch.status not in [BatchStatus.CREATED, BatchStatus.PAUSED]:
		raise HTTPException(
			status_code=400,
			detail=f"Cannot start batch with status {batch.status.value}"
		)

	batch.status = BatchStatus.IN_PROGRESS
	batch.started_at = batch.started_at or datetime.utcnow()
	batch.updated_at = datetime.utcnow()

	await db.commit()
	await db.refresh(batch)
	return batch


@router.post("/{batch_id}/pause", response_model=ScanBatchSchema)
async def pause_batch(
	batch_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Pause scanning for a batch."""
	result = await db.execute(
		select(ScanBatch).where(ScanBatch.id == batch_id)
	)
	batch = result.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	if batch.status != BatchStatus.IN_PROGRESS:
		raise HTTPException(
			status_code=400,
			detail="Can only pause an in-progress batch"
		)

	batch.status = BatchStatus.PAUSED
	batch.updated_at = datetime.utcnow()

	await db.commit()
	await db.refresh(batch)
	return batch


@router.post("/{batch_id}/complete", response_model=ScanBatchSchema)
async def complete_batch(
	batch_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Mark a batch as completed."""
	result = await db.execute(
		select(ScanBatch).where(ScanBatch.id == batch_id)
	)
	batch = result.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	batch.status = BatchStatus.COMPLETED
	batch.completed_at = datetime.utcnow()
	batch.updated_at = datetime.utcnow()

	await db.commit()
	await db.refresh(batch)
	return batch


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_batch(
	batch_id: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	user: Annotated[User, Depends(get_current_user)],
):
	"""Delete a scan batch."""
	result = await db.execute(
		select(ScanBatch).where(ScanBatch.id == batch_id)
	)
	batch = result.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	if batch.status == BatchStatus.IN_PROGRESS:
		raise HTTPException(
			status_code=400,
			detail="Cannot delete an in-progress batch"
		)

	await db.delete(batch)
	await db.commit()
