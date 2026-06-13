# (c) Copyright Datacraft, 2026
"""Image processing endpoints — camera capture and multi-image stitching."""
import base64
import json
import logging
from typing import Annotated

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_db
from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes
from papermerge.core.features.users.schema import User
from .image_processing import adaptive_deskew, autocrop_to_content, perspective_correct

router = APIRouter(
	prefix="/scanning-projects",
	tags=["scanning-projects-imaging"],
)

_log = logging.getLogger(__name__)


@router.post("/camera/process")
async def process_camera_image(
	user: Annotated[User, Depends(require_scopes(scopes.NODE_CREATE))],
	db: Annotated[AsyncSession, Depends(get_db)],
	file: UploadFile = File(...),
	corners: str | None = None,
	apply_deskew: bool = True,
	apply_autocrop: bool = True,
):
	"""Apply perspective correction, deskew, and autocrop to a camera-captured image."""
	data = await file.read()
	if len(data) > 50 * 1024 * 1024:
		raise HTTPException(status_code=413, detail="Image too large (max 50 MB)")

	parsed_corners: list[list[float]] | None = None
	if corners:
		try:
			parsed_corners = json.loads(corners)
		except (json.JSONDecodeError, ValueError):
			raise HTTPException(status_code=422, detail="corners must be JSON array [[x,y],...]")

	try:
		result = perspective_correct(data, parsed_corners)
		if apply_deskew:
			result = adaptive_deskew(result)
		if apply_autocrop:
			result = autocrop_to_content(result)
	except Exception as exc:
		_log.warning("Image processing failed: %s", exc)
		result = data

	# Quick quality check using existing assessment module
	quality_score: float | None = None
	defects: list[str] = []
	try:
		from papermerge.core.features.quality.assessment import assess_page_quality
		arr = np.frombuffer(result, dtype=np.uint8)
		img_arr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
		if img_arr is not None:
			metrics = assess_page_quality(img_arr)
			quality_score = round(metrics.quality_score / 100.0, 3)
			defects = [i.issue_type for i in metrics.issues]
	except Exception:
		pass

	# Decode final dimensions
	arr2 = np.frombuffer(result, dtype=np.uint8)
	out_img = cv2.imdecode(arr2, cv2.IMREAD_COLOR)
	h, w = (out_img.shape[:2] if out_img is not None else (0, 0))

	return {
		"processed_image_b64": base64.b64encode(result).decode(),
		"width": w,
		"height": h,
		"quality_score": quality_score,
		"defects": defects,
	}


@router.post("/stitch-images/from-uploads")
async def stitch_images(
	user: Annotated[User, Depends(require_scopes(scopes.NODE_CREATE))],
	db: Annotated[AsyncSession, Depends(get_db)],
	files: list[UploadFile] = File(...),
):
	"""Stitch 2–8 overlapping images of the same document into one."""
	if not (2 <= len(files) <= 8):
		raise HTTPException(status_code=422, detail="Provide 2–8 images to stitch")

	images: list[np.ndarray] = []
	for f in files:
		data = await f.read()
		arr = np.frombuffer(data, dtype=np.uint8)
		img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
		if img is None:
			raise HTTPException(status_code=422, detail=f"Could not decode image: {f.filename}")
		images.append(img)

	stitcher = cv2.Stitcher.create(cv2.Stitcher_SCANS)
	status, stitched = stitcher.stitch(images)

	if status != cv2.Stitcher_OK:
		_log.warning("Stitcher failed with status %d", status)
		return {
			"stitched_image_b64": None,
			"width": None,
			"height": None,
			"confidence": 0.0,
			"error": "stitch_failed",
			"status_code": status,
		}

	# Autocrop stitching seam margins
	ok, raw_bytes = cv2.imencode(".jpg", stitched, [cv2.IMWRITE_JPEG_QUALITY, 92])
	if not ok:
		raise HTTPException(status_code=500, detail="Failed to encode stitched image")

	cropped_bytes = autocrop_to_content(raw_bytes.tobytes())
	arr3 = np.frombuffer(cropped_bytes, dtype=np.uint8)
	out = cv2.imdecode(arr3, cv2.IMREAD_COLOR)
	h, w = (out.shape[:2] if out is not None else (0, 0))

	return {
		"stitched_image_b64": base64.b64encode(cropped_bytes).decode(),
		"width": w,
		"height": h,
		"confidence": 1.0,
		"error": None,
	}
