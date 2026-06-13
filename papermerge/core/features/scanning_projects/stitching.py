"""Multi-image document stitching using OpenCV."""
import logging
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

try:
	import cv2
	import numpy as np
	_CV2_AVAILABLE = True
except ImportError:
	_CV2_AVAILABLE = False
	cv2 = None  # type: ignore[assignment]
	np = None   # type: ignore[assignment]

logger = logging.getLogger(__name__)


class StitchStatus(str, Enum):
	OK = "ok"
	FAILED = "failed"
	NEED_MORE_IMAGES = "need_more_images"
	NOT_ENOUGH_OVERLAP = "not_enough_overlap"


@dataclass
class StitchResult:
	status: StitchStatus
	image: "np.ndarray | None"  # stitched result; None on failure
	confidence: float            # 0.0–1.0
	images_used: int
	error_message: str | None = field(default=None)


def stitch_document_images(
	image_paths: list[Path],
	min_overlap: float = 0.15,
) -> "StitchResult":
	"""Stitch multiple overlapping document images into one using cv2.Stitcher_SCANS.

	Falls back gracefully: tries SCANS mode first, then PANORAMA, then returns FAILED.
	Post-stitching: autocrop to document boundary.

	Args:
		image_paths: Ordered list of image file paths to stitch.
		min_overlap: Minimum expected fractional overlap between adjacent images.
		             Used only for validation feedback; OpenCV handles the actual
		             feature matching internally.

	Returns:
		StitchResult with status, stitched image array, confidence, and count.
	"""
	if not _CV2_AVAILABLE:
		return StitchResult(
			status=StitchStatus.FAILED,
			image=None,
			confidence=0.0,
			images_used=0,
			error_message="opencv-python is not installed",
		)

	if len(image_paths) < 2:
		return StitchResult(
			status=StitchStatus.NEED_MORE_IMAGES,
			image=None,
			confidence=0.0,
			images_used=len(image_paths),
			error_message=f"Need at least 2 images; got {len(image_paths)}",
		)

	# Load images
	imgs: list["np.ndarray"] = []
	for p in image_paths:
		img = cv2.imread(str(p))
		if img is None:
			return StitchResult(
				status=StitchStatus.FAILED,
				image=None,
				confidence=0.0,
				images_used=0,
				error_message=f"Failed to read image: {p}",
			)
		imgs.append(img)

	# Attempt stitching: SCANS first (flat/planar), PANORAMA as fallback
	modes = [
		("SCANS", cv2.Stitcher_SCANS),
		("PANORAMA", cv2.Stitcher_PANORAMA),
	]
	last_error: str = ""
	for mode_name, mode_flag in modes:
		stitcher = cv2.Stitcher_create(mode_flag)
		# Tighten confidence threshold relative to expected overlap
		# cv2 default confidence_threshold is 1.0; lower it slightly for documents
		# that may have limited texture in margins.
		stitcher.setPanoConfidenceThresh(max(0.5, 1.0 - min_overlap))

		status_code, result = stitcher.stitch(imgs)

		if status_code == cv2.Stitcher_OK:
			logger.info("Stitched %d images using %s mode", len(imgs), mode_name)
			cropped = autocrop_to_content(result)
			return StitchResult(
				status=StitchStatus.OK,
				image=cropped,
				confidence=_estimate_confidence(imgs, cropped),
				images_used=len(imgs),
			)

		err_label = _stitcher_error_label(status_code)
		last_error = f"{mode_name}: {err_label} (code {status_code})"
		logger.warning("Stitch attempt failed – %s", last_error)

	# Both modes failed — diagnose the likely cause
	stitch_status = StitchStatus.NOT_ENOUGH_OVERLAP if "ERR_NEED_MORE_IMGS" not in last_error else StitchStatus.FAILED
	return StitchResult(
		status=stitch_status,
		image=None,
		confidence=0.0,
		images_used=len(imgs),
		error_message=last_error,
	)


def autocrop_to_content(img: "np.ndarray", border_thresh: int = 240) -> "np.ndarray":
	"""Crop white/light borders from a stitched image.

	Args:
		img: BGR image array.
		border_thresh: Pixel intensity below which content is considered non-background.
		               240 catches near-white scanner margins.

	Returns:
		Cropped image; returns original if no crop region found.
	"""
	gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
	# Invert: dark pixels (content) become bright, bright border becomes dark
	_, mask = cv2.threshold(gray, border_thresh, 255, cv2.THRESH_BINARY_INV)

	coords = cv2.findNonZero(mask)
	if coords is None:
		return img  # all white — nothing to crop to

	x, y, w, h = cv2.boundingRect(coords)
	# Add a small margin so we don't clip hard at content edge
	margin = 4
	x = max(0, x - margin)
	y = max(0, y - margin)
	w = min(img.shape[1] - x, w + 2 * margin)
	h = min(img.shape[0] - y, h + 2 * margin)
	return img[y : y + h, x : x + w]


def encode_image(
	img: "np.ndarray",
	output_format: str,
) -> bytes:
	"""Encode a BGR numpy array to the requested format bytes.

	Args:
		img: BGR image array.
		output_format: One of "jpeg", "png", "tiff".

	Returns:
		Encoded image bytes.

	Raises:
		ValueError: For unsupported format.
		RuntimeError: If cv2.imencode fails.
	"""
	fmt_map = {
		"jpeg": ".jpg",
		"jpg": ".jpg",
		"png": ".png",
		"tiff": ".tiff",
		"tif": ".tiff",
	}
	ext = fmt_map.get(output_format.lower())
	if ext is None:
		raise ValueError(f"Unsupported output format: {output_format!r}")

	ok, buf = cv2.imencode(ext, img)
	if not ok:
		raise RuntimeError(f"cv2.imencode failed for format {output_format!r}")
	return buf.tobytes()


def save_stitched_temp(img: "np.ndarray", output_format: str) -> Path:
	"""Write stitched image to a named temp file and return the path.

	Caller is responsible for unlinking the file when done.
	"""
	ext_map = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "tiff": ".tiff"}
	ext = ext_map.get(output_format.lower(), ".jpg")
	with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
		tmp_path = Path(tmp.name)
	cv2.imwrite(str(tmp_path), img)
	return tmp_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stitcher_error_label(code: int) -> str:
	labels = {
		0: "OK",
		1: "ERR_NEED_MORE_IMGS",
		2: "ERR_HOMOGRAPHY_EST_FAIL",
		3: "ERR_CAMERA_PARAMS_ADJUST_FAIL",
	}
	return labels.get(code, f"UNKNOWN({code})")


def _estimate_confidence(
	source_imgs: "list[np.ndarray]",
	result: "np.ndarray",
) -> float:
	"""Heuristic confidence: ratio of result area to sum of source areas, clamped to [0,1].

	For a good stitch with ~50% overlap the result will be ~50-100% of total source area.
	A perfect linear stitch of N non-overlapping images would equal 1.0 × total area.
	We report the inverse of the overlap fraction as a proxy for "how complete" the
	assembly is — higher is better.
	"""
	total_source_px = sum(img.shape[0] * img.shape[1] for img in source_imgs)
	result_px = result.shape[0] * result.shape[1]
	if total_source_px == 0:
		return 0.0
	ratio = result_px / total_source_px
	# ratio > 1.0 is theoretically impossible but guard anyway
	return round(min(1.0, ratio), 4)
