"""
Automatic remediation for fixable scan defects.

Auto-fixable defects (applied in order):
  - skewed: apply adaptive deskew
  - blurry: flag only (no fix possible without rescanning)
  - low_contrast / background_noise: histogram normalization
  - orientation_error: rotate 90/180/270 based on detected angle

Returns the corrected image bytes and a list of applied fixes.
"""
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

try:
	import cv2
	import numpy as np
	_CV2_AVAILABLE = True
except ImportError:
	_CV2_AVAILABLE = False


@dataclass
class AutoFixResult:
	success: bool
	applied_fixes: list[str] = field(default_factory=list)
	skipped_defects: list[str] = field(default_factory=list)
	output_bytes: bytes | None = None
	error: str | None = None


_AUTO_FIXABLE = {"skewed", "low_contrast", "background_noise", "orientation_error"}


def can_auto_fix(defects: list[str]) -> bool:
	"""Return True if every detected defect is in the auto-fixable set."""
	return bool(defects) and all(d in _AUTO_FIXABLE for d in defects)


def auto_fix_image(image_bytes: bytes, defects: list[str]) -> AutoFixResult:
	"""Apply automatic fixes for fixable defects.

	Non-fixable defects (blurry, glare, document_cutoff) are skipped.
	"""
	if not _CV2_AVAILABLE:
		return AutoFixResult(success=False, error="opencv-python not installed")

	try:
		from PIL import Image
		from io import BytesIO
		import numpy as _np

		pil = Image.open(BytesIO(image_bytes)).convert("RGB")
		arr = _np.array(pil)
		img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
	except Exception as exc:
		return AutoFixResult(success=False, error=f"Could not decode image: {exc}")

	applied: list[str] = []
	skipped: list[str] = []

	for defect in defects:
		if defect == "skewed":
			try:
				from papermerge.core.features.scanning_projects.deskew import deskew_image
				gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
				corrected = deskew_image(gray)
				img = cv2.cvtColor(corrected, cv2.COLOR_GRAY2BGR)
				applied.append("skewed")
			except Exception as exc:
				log.debug("Deskew fix failed: %s", exc)
				skipped.append("skewed")

		elif defect in ("low_contrast", "background_noise"):
			try:
				# CLAHE (Contrast Limited Adaptive Histogram Equalization)
				lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
				l_ch, a_ch, b_ch = cv2.split(lab)
				clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
				l_ch = clahe.apply(l_ch)
				img = cv2.cvtColor(cv2.merge([l_ch, a_ch, b_ch]), cv2.COLOR_LAB2BGR)
				applied.append(defect)
			except Exception as exc:
				log.debug("Contrast fix failed: %s", exc)
				skipped.append(defect)

		elif defect == "orientation_error":
			try:
				gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
				coords = np.column_stack(np.where(gray < 128))
				if len(coords) > 100:
					angle = cv2.minAreaRect(coords)[-1]
					if angle < -45:
						angle = 90 + angle
					if abs(angle) > 45:
						img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE if angle > 0 else cv2.ROTATE_90_CLOCKWISE)
						applied.append("orientation_error")
					else:
						skipped.append("orientation_error")
			except Exception as exc:
				log.debug("Orientation fix failed: %s", exc)
				skipped.append("orientation_error")

		else:
			skipped.append(defect)

	# Encode result
	try:
		ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
		if not ok:
			return AutoFixResult(success=False, error="Could not encode output image")
		output_bytes = buf.tobytes()
	except Exception as exc:
		return AutoFixResult(success=False, error=f"Encode failed: {exc}")

	return AutoFixResult(
		success=len(applied) > 0,
		applied_fixes=applied,
		skipped_defects=skipped,
		output_bytes=output_bytes,
	)
