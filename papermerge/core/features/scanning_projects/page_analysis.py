# (c) Copyright Datacraft, 2026
"""Page-level analysis: blank detection and separator sheet detection.

Detects:
  - Blank pages (near-white pixel ratio threshold)
  - Separator sheets (blank or barcode-only page with a known prefix)

Dependencies (soft):
  - cv2 (opencv-python): required for blank detection
  - pyzbar or zxingcpp: required for barcode detection; falls back gracefully
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)

try:
	import cv2
	import numpy as np
	_CV2_AVAILABLE = True
except ImportError:
	_CV2_AVAILABLE = False

# Try pyzbar first, then zxingcpp as fallback
_BARCODE_LIB: str | None = None
try:
	from pyzbar import pyzbar as _pyzbar  # type: ignore
	_BARCODE_LIB = "pyzbar"
except ImportError:
	pass

if _BARCODE_LIB is None:
	try:
		import zxingcpp as _zxingcpp  # type: ignore
		_BARCODE_LIB = "zxingcpp"
	except ImportError:
		pass


@dataclass
class PageAnalysisResult:
	"""Result of a single-page separator/blank analysis pass."""

	is_blank: bool = False
	blank_ratio: float = 0.0          # fraction of near-white pixels (0.0–1.0)
	is_separator: bool = False
	separator_type: str | None = None  # "blank" | "barcode_separator"
	detected_barcodes: list[str] = field(default_factory=list)

	# Human-readable summary for logging/exception events
	def summary(self) -> str:
		if self.is_blank:
			return f"blank page (white_ratio={self.blank_ratio:.3f})"
		if self.is_separator and self.separator_type == "barcode_separator":
			return f"barcode separator: {self.detected_barcodes}"
		return "normal page"


def analyze_page_for_separator(
	image_data: bytes,
	separator_barcode_prefix: str = "",
	blank_threshold: float = 0.97,
) -> PageAnalysisResult:
	"""Detect blank pages and separator sheets.

	Blank detection:
	  Convert to grayscale, count pixels >= 240.  If white_ratio >= blank_threshold
	  the page is considered blank AND a separator.

	Barcode separator:
	  If barcodes are detected AND every barcode value starts with
	  ``separator_barcode_prefix`` (non-empty), the page is a separator sheet.

	Args:
		image_data: Raw image bytes (JPEG / PNG / any cv2-decodable format).
		separator_barcode_prefix: Prefix that marks a barcode as a separator
			(e.g. "SEP-").  Empty string disables barcode separator detection.
		blank_threshold: White-pixel fraction that triggers blank classification.
			Default 0.97 (97 %).

	Returns:
		PageAnalysisResult populated with detection outcomes.
	"""
	result = PageAnalysisResult()

	if not _CV2_AVAILABLE:
		_log.warning(
			"page_analysis: cv2 not available — skipping blank/separator detection"
		)
		return result

	# ── Decode ────────────────────────────────────────────────────────────────
	try:
		arr = np.frombuffer(image_data, dtype=np.uint8)
		img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
		if img is None:
			_log.warning("page_analysis: failed to decode image bytes")
			return result
	except Exception as exc:
		_log.warning("page_analysis: image decode error: %s", exc)
		return result

	# ── Blank detection ───────────────────────────────────────────────────────
	try:
		gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
		total_pixels = gray.size
		white_pixels = int(np.sum(gray >= 240))
		white_ratio = white_pixels / total_pixels if total_pixels > 0 else 0.0
		result.blank_ratio = round(white_ratio, 4)

		if white_ratio >= blank_threshold:
			result.is_blank = True
			result.is_separator = True
			result.separator_type = "blank"
			_log.debug("page_analysis: blank page detected (ratio=%.3f)", white_ratio)
			return result  # no need to run barcode detection on a blank page
	except Exception as exc:
		_log.warning("page_analysis: blank detection error: %s", exc)

	# ── Barcode detection ─────────────────────────────────────────────────────
	if not separator_barcode_prefix:
		return result

	barcodes: list[str] = _detect_barcodes(img)
	result.detected_barcodes = barcodes

	if barcodes and all(bc.startswith(separator_barcode_prefix) for bc in barcodes):
		result.is_separator = True
		result.separator_type = "barcode_separator"
		_log.debug(
			"page_analysis: barcode separator detected — barcodes=%s", barcodes
		)

	return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _detect_barcodes(img: "np.ndarray") -> list[str]:
	"""Attempt barcode detection using whichever library is available."""
	if _BARCODE_LIB is None:
		return []

	try:
		if _BARCODE_LIB == "pyzbar":
			return _detect_pyzbar(img)
		else:
			return _detect_zxingcpp(img)
	except Exception as exc:
		_log.debug("page_analysis: barcode detection error (%s): %s", _BARCODE_LIB, exc)
		return []


def _detect_pyzbar(img: "np.ndarray") -> list[str]:
	from pyzbar import pyzbar  # type: ignore
	decoded = pyzbar.decode(img)
	return [obj.data.decode("utf-8", errors="replace") for obj in decoded]


def _detect_zxingcpp(img: "np.ndarray") -> list[str]:
	import zxingcpp  # type: ignore
	results = zxingcpp.read_barcodes(img)
	return [r.text for r in results]


# ── Project-code extraction ───────────────────────────────────────────────────

def extract_project_code_from_barcode(
	barcodes: list[str],
	pattern: str,
) -> str | None:
	"""Extract a project code from a list of detected barcode values.

	Scans *barcodes* in order and returns the first match against:
	  ``^{re.escape(pattern)}(.+?)(-SEP)?$``

	The captured group (group 1) is returned; the optional trailing ``-SEP``
	suffix is stripped.

	Examples::

	  extract_project_code_from_barcode(["PROJ-2024-001-SEP"], "PROJ-")
	  # → "2024-001"

	  extract_project_code_from_barcode(["PROJ-2024-001"], "PROJ-")
	  # → "2024-001"

	  extract_project_code_from_barcode(["OTHER-123"], "PROJ-")
	  # → None

	Args:
		barcodes: Raw barcode values decoded from the page image.
		pattern: Literal prefix to match (e.g. ``"PROJ-"``).  Empty string
			disables extraction and returns ``None``.

	Returns:
		The extracted project code, or ``None`` if no match.
	"""
	if not pattern:
		return None

	import re as _re
	rx = _re.compile(r"^" + _re.escape(pattern) + r"(.+?)(-SEP)?$")
	for barcode in barcodes:
		m = rx.match(barcode)
		if m:
			code = m.group(1)
			_log.debug(
				"extract_project_code_from_barcode: matched %r → code=%r",
				barcode,
				code,
			)
			return code

	return None


# ── Multi-document gap detection ──────────────────────────────────────────────

def detect_multi_document_gap(
	page_sequence: list[PageAnalysisResult],
) -> list[int]:
	"""Return indices where document boundaries are detected in a page sequence.

	A document boundary exists at index *i* when ``page_sequence[i]`` is a
	separator page (``is_separator=True``).  These are the points at which the
	scan stream should be split into separate documents.

	Args:
		page_sequence: Ordered list of ``PageAnalysisResult`` objects, one per
			scanned page in acquisition order.

	Returns:
		List of zero-based indices (within *page_sequence*) that are separator
		pages.  The list is sorted ascending and may be empty.
	"""
	return [i for i, result in enumerate(page_sequence) if result.is_separator]
