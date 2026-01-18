# (c) Copyright Datacraft, 2026
"""
Multi-document segmentation feature.

Detects and splits multiple documents from a single scanned image.
Provides API endpoints for managing segments and reviewing detected documents.
"""
from .router import router
from .schema import (
	SegmentationRequest,
	SegmentSchema,
	SegmentListResponse,
	SegmentationJobSchema,
	SegmentationJobResponse,
	SegmentationMethodEnum,
	SegmentStatusEnum,
)
from .db import (
	ScanSegment,
	SegmentationJob,
	SegmentationMethod,
	SegmentStatus,
)

__all__ = [
	'router',
	'SegmentationRequest',
	'SegmentSchema',
	'SegmentListResponse',
	'SegmentationJobSchema',
	'SegmentationJobResponse',
	'SegmentationMethodEnum',
	'SegmentStatusEnum',
	'ScanSegment',
	'SegmentationJob',
	'SegmentationMethod',
	'SegmentStatus',
]
