# (c) Copyright Datacraft, 2026
"""OpenCV-based image processing — perspective correction, deskew, autocrop."""
import logging

import cv2
import numpy as np

_log = logging.getLogger(__name__)


def perspective_correct(
	image_bytes: bytes,
	corners: list[list[float]] | None = None,
) -> bytes:
	"""Perspective-correct a captured image.

	corners: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] TL/TR/BR/BL order.
	If None, auto-detect largest quadrilateral contour.
	"""
	img = _decode(image_bytes)
	h, w = img.shape[:2]

	if corners is None:
		corners = _auto_detect_corners(img)
		if corners is None:
			return image_bytes  # nothing to correct

	src = np.array(corners, dtype=np.float32)

	# Compute output dimensions from top-edge and left-edge lengths
	width = int(max(
		np.linalg.norm(src[1] - src[0]),
		np.linalg.norm(src[2] - src[3]),
	))
	height = int(max(
		np.linalg.norm(src[3] - src[0]),
		np.linalg.norm(src[2] - src[1]),
	))
	if width < 10 or height < 10:
		return image_bytes

	dst = np.array([
		[0, 0],
		[width - 1, 0],
		[width - 1, height - 1],
		[0, height - 1],
	], dtype=np.float32)

	M = cv2.getPerspectiveTransform(src, dst)
	corrected = cv2.warpPerspective(img, M, (width, height), flags=cv2.INTER_LINEAR)
	return _encode(corrected)


def adaptive_deskew(image_bytes: bytes) -> bytes:
	"""Deskew using projection profile analysis (97.6% accuracy).

	Delegates to :func:`papermerge.core.features.scanning_projects.deskew.adaptive_deskew`
	which uses horizontal projection profile variance maximisation instead of the
	legacy probabilistic Hough transform.
	"""
	try:
		from papermerge.core.features.scanning_projects.deskew import (
			adaptive_deskew as _proj_deskew,
		)
		img = _decode(image_bytes)
		corrected, _angle = _proj_deskew(img)
		return _encode(corrected)
	except Exception as exc:
		_log.warning("adaptive_deskew failed (%s); returning original image bytes", exc)
		return image_bytes


def autocrop_to_content(image_bytes: bytes, padding: int = 20) -> bytes:
	"""Crop away uniform border around document content."""
	img = _decode(image_bytes)
	gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
	_, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
	contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
	if not contours:
		return image_bytes

	all_pts = np.concatenate(contours)
	x, y, cw, ch = cv2.boundingRect(all_pts)
	h, w = img.shape[:2]
	x1 = max(0, x - padding)
	y1 = max(0, y - padding)
	x2 = min(w, x + cw + padding)
	y2 = min(h, y + ch + padding)
	cropped = img[y1:y2, x1:x2]
	return _encode(cropped)


def _auto_detect_corners(img: np.ndarray) -> list[list[float]] | None:
	gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
	blurred = cv2.GaussianBlur(gray, (5, 5), 0)
	edges = cv2.Canny(blurred, 50, 150)
	contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
	if not contours:
		return None

	contours = sorted(contours, key=cv2.contourArea, reverse=True)
	for c in contours[:5]:
		peri = cv2.arcLength(c, True)
		approx = cv2.approxPolyDP(c, 0.02 * peri, True)
		if len(approx) == 4:
			pts = approx.reshape(4, 2).tolist()
			# Sort TL/TR/BR/BL
			s = sorted(pts, key=lambda p: p[0] + p[1])
			tl, br = s[0], s[-1]
			remaining = [p for p in pts if p not in (tl, br)]
			tr = min(remaining, key=lambda p: p[1] - p[0])
			bl = max(remaining, key=lambda p: p[1] - p[0])
			return [tl, tr, br, bl]
	return None


def _decode(data: bytes) -> np.ndarray:
	arr = np.frombuffer(data, dtype=np.uint8)
	img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
	if img is None:
		raise ValueError("Could not decode image bytes")
	return img


def _encode(img: np.ndarray, quality: int = 92) -> bytes:
	ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
	if not ok:
		raise RuntimeError("JPEG encode failed")
	return buf.tobytes()
