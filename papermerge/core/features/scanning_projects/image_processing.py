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


def detect_rotation(image: np.ndarray) -> int:
	"""Detect if an image is rotated 90, 180, or 270 degrees (not minor skew — major rotation).

	Returns 0, 90, 180, or 270 (degrees to rotate CCW to correct).

	Strategy: projection profile analysis.
	For each candidate rotation (0, 90, 180, 270): rotate the image, compute the
	horizontal text-line projection profile (row sums on binarised image).
	The correct orientation has the highest variance in the horizontal projection
	because text lines form distinct dense rows separated by whitespace.
	Returns the rotation angle with maximum projection variance.
	"""
	try:
		# Grayscale + binarise (Otsu, text = white on black)
		if len(image.shape) == 3:
			gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
		else:
			gray = image.copy()
		_, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

		def _projection_variance(rot_code: int | None) -> float:
			"""Return row-sum variance of binary after optional 90° rotation."""
			if rot_code is None:
				rotated = binary
			else:
				rotated = cv2.rotate(binary, rot_code)
			row_sums = rotated.sum(axis=1).astype(np.float64)
			return float(row_sums.var())

		# cv2.rotate codes for CCW corrections:
		#   to correct a 90° CW scan  → rotate 90° CCW  → ROTATE_90_COUNTERCLOCKWISE
		#   to correct a 180° scan    → rotate 180°      → ROTATE_180
		#   to correct a 270° CW scan → rotate 90° CW    → ROTATE_90_CLOCKWISE
		candidates: list[tuple[int, int | None]] = [
			(0,   None),
			(90,  cv2.ROTATE_90_COUNTERCLOCKWISE),
			(180, cv2.ROTATE_180),
			(270, cv2.ROTATE_90_CLOCKWISE),
		]

		best_angle = 0
		best_var = -1.0
		for angle, rot_code in candidates:
			var = _projection_variance(rot_code)
			if var > best_var:
				best_var = var
				best_angle = angle

		return best_angle

	except Exception as exc:
		_log.warning("detect_rotation failed (%s); assuming 0°", exc)
		return 0


def correct_rotation(image: np.ndarray) -> tuple[np.ndarray, int]:
	"""Detect and apply major rotation correction (90 / 180 / 270 degrees only).

	Returns (corrected_image, degrees_rotated).
	Returns the original image unchanged when no rotation is needed (0°).
	"""
	angle = detect_rotation(image)
	if angle == 0:
		return image, 0

	rot_map = {
		90:  cv2.ROTATE_90_COUNTERCLOCKWISE,
		180: cv2.ROTATE_180,
		270: cv2.ROTATE_90_CLOCKWISE,
	}
	corrected = cv2.rotate(image, rot_map[angle])
	_log.info("auto-rotation: corrected %d° CCW", angle)
	return corrected, angle


def get_rotation_info(image_data: bytes) -> dict:
	"""Return rotation detection metadata for raw image bytes.

	Returns::

		{"detected_rotation": int, "corrected": bool}

	``detected_rotation`` is one of 0 / 90 / 180 / 270 (CCW degrees needed to
	correct the image).  ``corrected`` is False when rotation is 0°.
	"""
	try:
		img = _decode(image_data)
		angle = detect_rotation(img)
		return {"detected_rotation": angle, "corrected": angle != 0}
	except Exception as exc:
		_log.warning("get_rotation_info failed (%s)", exc)
		return {"detected_rotation": 0, "corrected": False}


def adaptive_deskew(image_bytes: bytes) -> bytes:
	"""Deskew using projection profile analysis (97.6% accuracy).

	Pipeline:
	1. Correct major rotation (90 / 180 / 270°) via projection-profile analysis.
	2. Run fine deskew on the rotation-corrected image.

	Delegates fine deskew to
	:func:`papermerge.core.features.scanning_projects.deskew.adaptive_deskew`.
	"""
	try:
		from papermerge.core.features.scanning_projects.deskew import (
			adaptive_deskew as _proj_deskew,
		)
		img = _decode(image_bytes)

		# Step 1: major rotation correction (before fine deskew)
		img, rotation_applied = correct_rotation(img)
		if rotation_applied:
			_log.info("adaptive_deskew: rotation correction applied (%d°)", rotation_applied)

		# Step 2: fine deskew
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
