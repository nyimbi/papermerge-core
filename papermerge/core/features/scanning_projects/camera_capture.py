"""Camera document capture with perspective correction."""
import base64
import io
from dataclasses import dataclass, field

import numpy as np

try:
	import cv2
	_CV2_AVAILABLE = True
except ImportError:
	_CV2_AVAILABLE = False


@dataclass
class CaptureConfig:
	calibration_pixels_per_mm: float | None = None  # from DPI calibration
	auto_detect_corners: bool = True
	target_dpi: int = 300
	output_format: str = "jpeg"  # jpeg, png, tiff


@dataclass
class PerspectiveResult:
	success: bool
	corrected_image: np.ndarray | None
	detected_corners: list[list[float]] | None  # [[x,y], [x,y], [x,y], [x,y]]
	estimated_dpi: float | None
	quality_score: float | None  # from OpenCV blur check (Laplacian variance)
	error: str | None


def _require_cv2() -> None:
	if not _CV2_AVAILABLE:
		raise RuntimeError("opencv-python is not installed; camera capture is unavailable")


def order_points(pts: np.ndarray) -> np.ndarray:
	"""
	Sort four corner points into [top-left, top-right, bottom-right, bottom-left] order.
	TL has smallest sum, BR has largest sum; TR has smallest diff, BL has largest diff.
	"""
	rect = np.zeros((4, 2), dtype=np.float32)
	s = pts.sum(axis=1)
	rect[0] = pts[np.argmin(s)]   # TL
	rect[2] = pts[np.argmax(s)]   # BR
	diff = np.diff(pts, axis=1)
	rect[1] = pts[np.argmin(diff)]  # TR
	rect[3] = pts[np.argmax(diff)]  # BL
	return rect


def detect_document_corners(img: np.ndarray) -> list[list[float]] | None:
	"""
	Detect document corners using OpenCV contour detection.
	Returns [[tl], [tr], [br], [bl]] corners or None if detection fails.
	Pipeline: grayscale -> blur -> Canny edges -> findContours -> approxPolyDP -> 4-point filter.
	"""
	_require_cv2()

	gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
	# Bilateral filter preserves edges while reducing noise
	blurred = cv2.bilateralFilter(gray, 9, 75, 75)
	# Canny with automatic threshold via Otsu
	_, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
	edges = cv2.Canny(thresh, 30, 100)

	# Dilate to close small gaps in edges
	kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
	dilated = cv2.dilate(edges, kernel, iterations=1)

	contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
	if not contours:
		return None

	# Sort by area descending; document should be the largest contour
	contours = sorted(contours, key=cv2.contourArea, reverse=True)

	h, w = img.shape[:2]
	image_area = h * w

	for contour in contours[:10]:
		area = cv2.contourArea(contour)
		# Skip tiny contours (< 10% of image) and full-image contours (> 99%)
		if area < image_area * 0.10 or area > image_area * 0.99:
			continue

		perimeter = cv2.arcLength(contour, True)
		approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)

		if len(approx) == 4:
			pts = approx.reshape(4, 2).astype(np.float32)
			ordered = order_points(pts)
			return ordered.tolist()

	return None


def apply_perspective_correction(
	img: np.ndarray,
	corners: list[list[float]],
	target_width_px: int | None = None,
) -> np.ndarray:
	"""
	Apply homographic perspective transform to rectify a document.
	Uses cv2.getPerspectiveTransform + cv2.warpPerspective.
	Infers output size from the convex hull of the four corners if target_width_px is None.
	"""
	_require_cv2()

	pts = np.array(corners, dtype=np.float32)
	ordered = order_points(pts)
	tl, tr, br, bl = ordered

	# Compute output dimensions from edge lengths
	width_top = np.linalg.norm(tr - tl)
	width_bottom = np.linalg.norm(br - bl)
	out_w = int(max(width_top, width_bottom))

	height_left = np.linalg.norm(bl - tl)
	height_right = np.linalg.norm(br - tr)
	out_h = int(max(height_left, height_right))

	if target_width_px is not None and out_w > 0:
		scale = target_width_px / out_w
		out_w = target_width_px
		out_h = int(out_h * scale)

	if out_w <= 0 or out_h <= 0:
		return img

	dst = np.array(
		[[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
		dtype=np.float32,
	)

	M = cv2.getPerspectiveTransform(ordered, dst)
	warped = cv2.warpPerspective(img, M, (out_w, out_h))
	return warped


def estimate_dpi_from_calibration(
	img: np.ndarray,
	known_width_mm: float,
	pixels_per_mm: float | None = None,
) -> float:
	"""
	Estimate scan DPI from document width in mm and image pixel width.
	If pixels_per_mm is provided it is used directly; otherwise pixel width / known_width_mm.
	DPI = pixels_per_mm * 25.4.
	"""
	if pixels_per_mm is not None:
		return pixels_per_mm * 25.4

	if known_width_mm <= 0:
		raise ValueError("known_width_mm must be > 0")

	pixel_width = img.shape[1]
	ppmm = pixel_width / known_width_mm
	return ppmm * 25.4


def _compute_quality_score(img: np.ndarray) -> float:
	"""Laplacian variance blur metric. Higher = sharper. Returns value >= 0."""
	_require_cv2()
	gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
	lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
	return float(lap_var)


def _encode_image(img: np.ndarray, fmt: str) -> bytes:
	"""Encode an OpenCV image array to bytes in the requested format."""
	_require_cv2()
	ext_map = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "tiff": ".tiff", "tif": ".tiff"}
	ext = ext_map.get(fmt.lower(), ".jpg")
	success, buf = cv2.imencode(ext, img)
	if not success:
		raise RuntimeError(f"cv2.imencode failed for format {fmt!r}")
	return buf.tobytes()


def process_camera_capture(
	image_bytes: bytes,
	config: CaptureConfig | None = None,
) -> PerspectiveResult:
	"""
	Full pipeline: decode -> detect corners -> correct perspective -> quality check.

	Steps:
	1. Decode raw bytes via cv2.imdecode.
	2. If config.auto_detect_corners: run detect_document_corners.
	3. If corners found: apply_perspective_correction.
	4. Compute Laplacian-variance quality score.
	5. Optionally estimate DPI from calibration_pixels_per_mm.
	"""
	if not _CV2_AVAILABLE:
		return PerspectiveResult(
			success=False,
			corrected_image=None,
			detected_corners=None,
			estimated_dpi=None,
			quality_score=None,
			error="opencv-python is not installed; camera capture is unavailable",
		)

	cfg = config or CaptureConfig()

	# Decode
	arr = np.frombuffer(image_bytes, dtype=np.uint8)
	img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
	if img is None:
		return PerspectiveResult(
			success=False,
			corrected_image=None,
			detected_corners=None,
			estimated_dpi=None,
			quality_score=None,
			error="Failed to decode image bytes; unsupported or corrupt format",
		)

	# Corner detection
	corners: list[list[float]] | None = None
	if cfg.auto_detect_corners:
		corners = detect_document_corners(img)

	# Perspective correction
	output_img = img
	if corners is not None:
		# Compute target pixel width for target_dpi if calibration available
		target_width_px: int | None = None
		if cfg.calibration_pixels_per_mm is not None:
			# A4 width = 210 mm as default; caller can override via corners implicitly
			target_width_px = int(cfg.calibration_pixels_per_mm * 210)
		output_img = apply_perspective_correction(img, corners, target_width_px)

	# Quality score
	quality_score = _compute_quality_score(output_img)

	# DPI estimation
	estimated_dpi: float | None = None
	if cfg.calibration_pixels_per_mm is not None:
		estimated_dpi = cfg.calibration_pixels_per_mm * 25.4
	elif corners is not None and output_img.shape[1] > 0:
		# Default assumption: output image represents A4 width (210 mm)
		estimated_dpi = estimate_dpi_from_calibration(output_img, known_width_mm=210.0)

	return PerspectiveResult(
		success=True,
		corrected_image=output_img,
		detected_corners=corners,
		estimated_dpi=estimated_dpi,
		quality_score=quality_score,
		error=None,
	)


def calibrate_from_a4(image_bytes: bytes) -> dict:
	"""
	Estimate pixels_per_mm from a photo of an A4 sheet (210 x 297 mm).
	Returns a dict with pixels_per_mm, estimated_dpi_at_current_distance, and instructions.
	"""
	if not _CV2_AVAILABLE:
		raise RuntimeError("opencv-python is not installed; camera capture is unavailable")

	arr = np.frombuffer(image_bytes, dtype=np.uint8)
	img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
	if img is None:
		raise ValueError("Failed to decode calibration image")

	corners = detect_document_corners(img)
	if corners is None:
		raise ValueError(
			"Could not detect document corners in calibration image. "
			"Ensure the A4 sheet is fully visible on a contrasting background."
		)

	# Rectify to get true pixel dimensions
	rectified = apply_perspective_correction(img, corners)
	pixel_width = rectified.shape[1]
	pixel_height = rectified.shape[0]

	# A4: 210 mm wide, 297 mm tall
	ppmm_w = pixel_width / 210.0
	ppmm_h = pixel_height / 297.0
	pixels_per_mm = (ppmm_w + ppmm_h) / 2.0
	estimated_dpi = pixels_per_mm * 25.4

	return {
		"pixels_per_mm": round(pixels_per_mm, 4),
		"estimated_dpi_at_current_distance": round(estimated_dpi, 1),
		"instructions": (
			"Hold the camera at this distance to achieve the indicated DPI. "
			"Use the returned pixels_per_mm value in subsequent /camera/process calls "
			"via the calibration_pixels_per_mm config parameter."
		),
	}


def enumerate_camera_devices(max_index: int = 10) -> list[dict]:
	"""
	Probe camera indices 0..max_index-1 via cv2.VideoCapture.
	Returns a list of dicts with index, width, height, fps for each available device.
	"""
	if not _CV2_AVAILABLE:
		raise RuntimeError("opencv-python is not installed; camera capture is unavailable")

	devices: list[dict] = []
	for idx in range(max_index):
		cap = cv2.VideoCapture(idx)
		if cap.isOpened():
			width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
			height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
			fps = cap.get(cv2.CAP_PROP_FPS)
			devices.append(
				{
					"index": idx,
					"width": width,
					"height": height,
					"fps": round(fps, 2),
					"label": f"Camera {idx} ({width}x{height})",
				}
			)
		cap.release()
	return devices
