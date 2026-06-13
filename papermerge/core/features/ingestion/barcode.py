"""
Server-side barcode and QR code detection using OpenCV.

Detects Code128, Code39, EAN-13, QR codes from uploaded images.
Used for scan-time dedup (re-scan prevention) and document identity assignment.
"""
import logging
from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

try:
	import cv2
	_CV2_AVAILABLE = True
except ImportError:
	_CV2_AVAILABLE = False


@dataclass
class BarcodeResult:
	value: str
	barcode_type: str
	confidence: float
	bbox: list[list[int]] | None = None


def detect_barcodes(data: bytes) -> list[BarcodeResult]:
	"""Detect all barcodes and QR codes in an image.

	Returns a list of BarcodeResult, sorted by confidence descending.
	Returns [] if cv2 unavailable or no codes found.
	"""
	if not _CV2_AVAILABLE:
		log.warning("cv2 not available — barcode detection skipped")
		return []

	try:
		img = Image.open(BytesIO(data)).convert("RGB")
		arr = np.array(img)
		gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
	except Exception as exc:
		log.debug("Could not decode image for barcode detection: %s", exc)
		return []

	results: list[BarcodeResult] = []

	# QR codes
	qr = cv2.QRCodeDetector()
	try:
		data_list, points, _ = qr.detectAndDecodeMulti(gray)
		if data_list:
			for val, pts in zip(data_list, points if points is not None else [None] * len(data_list)):
				if val:
					bbox = pts.astype(int).tolist() if pts is not None else None
					results.append(BarcodeResult(value=val, barcode_type="QR_CODE", confidence=0.95, bbox=bbox))
	except Exception as exc:
		log.debug("QR detection error: %s", exc)

	# Linear barcodes (Code128, Code39, EAN, etc.)
	try:
		detector = cv2.barcode.BarcodeDetector()
		ok, decoded_info, decoded_type, points = detector.detectAndDecode(gray)
		if ok and decoded_info:
			for val, btype, pts in zip(decoded_info, decoded_type, points if points is not None else [None] * len(decoded_info)):
				if val:
					bbox = pts.astype(int).tolist() if pts is not None else None
					results.append(BarcodeResult(value=val, barcode_type=btype or "BARCODE", confidence=0.90, bbox=bbox))
	except Exception as exc:
		log.debug("Barcode detection error: %s", exc)

	results.sort(key=lambda r: r.confidence, reverse=True)
	return results
