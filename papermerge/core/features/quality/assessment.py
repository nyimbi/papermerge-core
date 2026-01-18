# (c) Copyright Datacraft, 2026
"""
Document quality assessment.

Analyzes scanned documents for quality metrics including:
- Resolution (DPI)
- Skew angle
- Brightness and contrast
- Sharpness and blur
- Noise levels
- OCR confidence
"""
import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)


class QualityGrade(str, Enum):
	"""Overall quality grade."""
	EXCELLENT = "excellent"  # 90-100
	GOOD = "good"  # 75-89
	ACCEPTABLE = "acceptable"  # 60-74
	POOR = "poor"  # 40-59
	UNACCEPTABLE = "unacceptable"  # 0-39


@dataclass
class QualityIssue:
	"""A quality issue found during assessment."""
	metric: str
	actual_value: float
	expected_value: float | None
	severity: str  # info, warning, error, critical
	message: str
	page_number: int | None = None
	auto_fixable: bool = False


@dataclass
class QualityMetrics:
	"""Quality metrics for a document or page."""
	# Image properties
	resolution_dpi: int | None = None
	width_px: int | None = None
	height_px: int | None = None
	file_size_bytes: int | None = None

	# Quality measurements
	skew_angle: float | None = None  # Degrees, 0 = no skew
	brightness: float | None = None  # 0-255, 127 = ideal
	contrast: float | None = None  # 0-1, higher = better
	sharpness: float | None = None  # 0-1, higher = sharper
	noise_level: float | None = None  # 0-1, lower = better
	blur_score: float | None = None  # 0-1, lower = sharper

	# OCR metrics
	ocr_confidence: float | None = None  # 0-1
	text_density: float | None = None  # Characters per page

	# Special detections
	is_blank: bool | None = None
	orientation: int | None = None  # 0, 90, 180, 270
	has_border: bool | None = None
	border_uniformity: float | None = None  # 0-1

	# Overall
	quality_score: float = 0.0
	grade: QualityGrade = QualityGrade.UNACCEPTABLE
	issues: list[QualityIssue] = field(default_factory=list)

	@property
	def passed(self) -> bool:
		"""Check if quality passes minimum threshold."""
		return self.quality_score >= 60.0

	@property
	def critical_issue_count(self) -> int:
		"""Count critical issues."""
		return sum(1 for i in self.issues if i.severity == "critical")


class QualityAssessor:
	"""
	Assesses document quality using image analysis.

	Uses OpenCV for image processing and analysis.
	"""

	def __init__(
		self,
		min_dpi: int = 200,
		max_skew_degrees: float = 2.0,
		min_brightness: float = 100.0,
		max_brightness: float = 200.0,
		min_contrast: float = 0.3,
		min_sharpness: float = 0.3,
		max_noise: float = 0.3,
		min_ocr_confidence: float = 0.7,
	):
		self.min_dpi = min_dpi
		self.max_skew_degrees = max_skew_degrees
		self.min_brightness = min_brightness
		self.max_brightness = max_brightness
		self.min_contrast = min_contrast
		self.min_sharpness = min_sharpness
		self.max_noise = max_noise
		self.min_ocr_confidence = min_ocr_confidence

	def assess_image(
		self,
		image_path: Path | str,
		ocr_confidence: float | None = None,
	) -> QualityMetrics:
		"""
		Assess quality of an image file.

		Args:
			image_path: Path to the image file
			ocr_confidence: Optional pre-computed OCR confidence

		Returns:
			QualityMetrics with all measurements and issues
		"""
		try:
			import cv2
			from PIL import Image
		except ImportError:
			logger.warning("OpenCV/PIL not available, returning basic metrics")
			return QualityMetrics()

		path = Path(image_path)
		metrics = QualityMetrics()
		metrics.file_size_bytes = path.stat().st_size

		# Load image
		img = cv2.imread(str(path))
		if img is None:
			metrics.issues.append(QualityIssue(
				metric="file_read",
				actual_value=0,
				expected_value=1,
				severity="critical",
				message="Failed to read image file",
			))
			return metrics

		# Get dimensions and DPI
		with Image.open(path) as pil_img:
			dpi = pil_img.info.get("dpi", (72, 72))
			metrics.resolution_dpi = int(min(dpi[0], dpi[1]))

		metrics.height_px, metrics.width_px = img.shape[:2]

		# Convert to grayscale for analysis
		gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

		# Analyze various metrics
		self._analyze_brightness(gray, metrics)
		self._analyze_contrast(gray, metrics)
		self._analyze_sharpness(gray, metrics)
		self._analyze_noise(gray, metrics)
		self._analyze_skew(gray, metrics)
		self._detect_blank_page(gray, metrics)
		self._detect_orientation(gray, metrics)

		# Add OCR confidence if provided
		if ocr_confidence is not None:
			metrics.ocr_confidence = ocr_confidence

		# Check against thresholds
		self._check_thresholds(metrics)

		# Calculate overall score
		self._calculate_score(metrics)

		return metrics

	def assess_from_array(
		self,
		image_array: np.ndarray,
		dpi: int | None = None,
		ocr_confidence: float | None = None,
	) -> QualityMetrics:
		"""
		Assess quality from a numpy array.

		Args:
			image_array: Image as numpy array (BGR or grayscale)
			dpi: Optional DPI value
			ocr_confidence: Optional pre-computed OCR confidence

		Returns:
			QualityMetrics with all measurements and issues
		"""
		try:
			import cv2
		except ImportError:
			logger.warning("OpenCV not available, returning basic metrics")
			return QualityMetrics()

		metrics = QualityMetrics()
		metrics.resolution_dpi = dpi

		if len(image_array.shape) == 3:
			gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
			metrics.height_px, metrics.width_px = image_array.shape[:2]
		else:
			gray = image_array
			metrics.height_px, metrics.width_px = image_array.shape

		# Analyze various metrics
		self._analyze_brightness(gray, metrics)
		self._analyze_contrast(gray, metrics)
		self._analyze_sharpness(gray, metrics)
		self._analyze_noise(gray, metrics)
		self._analyze_skew(gray, metrics)
		self._detect_blank_page(gray, metrics)
		self._detect_orientation(gray, metrics)

		if ocr_confidence is not None:
			metrics.ocr_confidence = ocr_confidence

		self._check_thresholds(metrics)
		self._calculate_score(metrics)

		return metrics

	def _analyze_brightness(self, gray: np.ndarray, metrics: QualityMetrics) -> None:
		"""Analyze image brightness."""
		metrics.brightness = float(np.mean(gray))

	def _analyze_contrast(self, gray: np.ndarray, metrics: QualityMetrics) -> None:
		"""Analyze image contrast using standard deviation."""
		std = np.std(gray)
		# Normalize to 0-1 range (max std for 8-bit is ~127)
		metrics.contrast = float(std / 127.0)

	def _analyze_sharpness(self, gray: np.ndarray, metrics: QualityMetrics) -> None:
		"""Analyze image sharpness using Laplacian variance."""
		try:
			import cv2
			laplacian = cv2.Laplacian(gray, cv2.CV_64F)
			variance = laplacian.var()
			# Normalize (typical values 0-5000+)
			metrics.sharpness = min(1.0, float(variance / 1000.0))
		except Exception as e:
			logger.warning(f"Failed to analyze sharpness: {e}")

	def _analyze_noise(self, gray: np.ndarray, metrics: QualityMetrics) -> None:
		"""Estimate noise level using median absolute deviation."""
		try:
			import cv2
			# Apply Gaussian blur and compare
			blurred = cv2.GaussianBlur(gray, (5, 5), 0)
			diff = np.abs(gray.astype(float) - blurred.astype(float))
			noise = np.median(diff) / 255.0
			metrics.noise_level = float(noise)
		except Exception as e:
			logger.warning(f"Failed to analyze noise: {e}")

	def _analyze_skew(self, gray: np.ndarray, metrics: QualityMetrics) -> None:
		"""Detect skew angle using Hough transform."""
		try:
			import cv2

			# Edge detection
			edges = cv2.Canny(gray, 50, 150, apertureSize=3)

			# Hough line detection
			lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)

			if lines is not None and len(lines) > 0:
				# Calculate average angle
				angles = []
				for line in lines[:20]:  # Use top 20 lines
					theta = line[0][1]
					angle = (theta * 180 / np.pi) - 90
					if abs(angle) < 45:  # Filter out near-vertical lines
						angles.append(angle)

				if angles:
					metrics.skew_angle = float(np.median(angles))
				else:
					metrics.skew_angle = 0.0
			else:
				metrics.skew_angle = 0.0
		except Exception as e:
			logger.warning(f"Failed to analyze skew: {e}")
			metrics.skew_angle = 0.0

	def _detect_blank_page(self, gray: np.ndarray, metrics: QualityMetrics) -> None:
		"""Detect if page is blank."""
		# A blank page has very low variance and high mean (white)
		mean_val = np.mean(gray)
		std_val = np.std(gray)

		# Blank if high brightness (>230) and low variance (<10)
		metrics.is_blank = mean_val > 230 and std_val < 10

	def _detect_orientation(self, gray: np.ndarray, metrics: QualityMetrics) -> None:
		"""Detect page orientation (0, 90, 180, 270)."""
		# Simple heuristic based on aspect ratio
		# More sophisticated detection would use text orientation
		h, w = gray.shape
		if w > h * 1.2:
			# Landscape - might be rotated 90 or 270
			metrics.orientation = None  # Uncertain
		else:
			metrics.orientation = 0  # Assume correct

	def _check_thresholds(self, metrics: QualityMetrics) -> None:
		"""Check metrics against thresholds and add issues."""
		# Resolution
		if metrics.resolution_dpi and metrics.resolution_dpi < self.min_dpi:
			metrics.issues.append(QualityIssue(
				metric="resolution_dpi",
				actual_value=metrics.resolution_dpi,
				expected_value=self.min_dpi,
				severity="error" if metrics.resolution_dpi < 150 else "warning",
				message=f"Low resolution: {metrics.resolution_dpi} DPI (minimum: {self.min_dpi})",
			))

		# Skew
		if metrics.skew_angle is not None and abs(metrics.skew_angle) > self.max_skew_degrees:
			severity = "error" if abs(metrics.skew_angle) > 5 else "warning"
			metrics.issues.append(QualityIssue(
				metric="skew_angle",
				actual_value=abs(metrics.skew_angle),
				expected_value=self.max_skew_degrees,
				severity=severity,
				message=f"Image is skewed by {abs(metrics.skew_angle):.1f} degrees",
				auto_fixable=True,
			))

		# Brightness
		if metrics.brightness is not None:
			if metrics.brightness < self.min_brightness:
				metrics.issues.append(QualityIssue(
					metric="brightness",
					actual_value=metrics.brightness,
					expected_value=self.min_brightness,
					severity="warning",
					message=f"Image is too dark (brightness: {metrics.brightness:.0f})",
					auto_fixable=True,
				))
			elif metrics.brightness > self.max_brightness:
				metrics.issues.append(QualityIssue(
					metric="brightness",
					actual_value=metrics.brightness,
					expected_value=self.max_brightness,
					severity="warning",
					message=f"Image is too bright (brightness: {metrics.brightness:.0f})",
					auto_fixable=True,
				))

		# Contrast
		if metrics.contrast is not None and metrics.contrast < self.min_contrast:
			metrics.issues.append(QualityIssue(
				metric="contrast",
				actual_value=metrics.contrast,
				expected_value=self.min_contrast,
				severity="warning",
				message=f"Low contrast: {metrics.contrast:.2f}",
				auto_fixable=True,
			))

		# Sharpness / Blur
		if metrics.sharpness is not None and metrics.sharpness < self.min_sharpness:
			severity = "error" if metrics.sharpness < 0.1 else "warning"
			metrics.issues.append(QualityIssue(
				metric="sharpness",
				actual_value=metrics.sharpness,
				expected_value=self.min_sharpness,
				severity=severity,
				message=f"Image is blurry (sharpness: {metrics.sharpness:.2f})",
			))

		# Noise
		if metrics.noise_level is not None and metrics.noise_level > self.max_noise:
			metrics.issues.append(QualityIssue(
				metric="noise_level",
				actual_value=metrics.noise_level,
				expected_value=self.max_noise,
				severity="warning",
				message=f"High noise level: {metrics.noise_level:.2f}",
				auto_fixable=True,
			))

		# OCR confidence
		if metrics.ocr_confidence is not None and metrics.ocr_confidence < self.min_ocr_confidence:
			severity = "error" if metrics.ocr_confidence < 0.5 else "warning"
			metrics.issues.append(QualityIssue(
				metric="ocr_confidence",
				actual_value=metrics.ocr_confidence,
				expected_value=self.min_ocr_confidence,
				severity=severity,
				message=f"Low OCR confidence: {metrics.ocr_confidence:.0%}",
			))

		# Blank page
		if metrics.is_blank:
			metrics.issues.append(QualityIssue(
				metric="blank_page",
				actual_value=1.0,
				expected_value=0.0,
				severity="info",
				message="Page appears to be blank",
			))

	def _calculate_score(self, metrics: QualityMetrics) -> None:
		"""Calculate overall quality score (0-100)."""
		scores = []
		weights = []

		# Resolution score (weight: 20)
		if metrics.resolution_dpi:
			if metrics.resolution_dpi >= 300:
				scores.append(100)
			elif metrics.resolution_dpi >= 200:
				scores.append(80)
			elif metrics.resolution_dpi >= 150:
				scores.append(60)
			elif metrics.resolution_dpi >= 100:
				scores.append(40)
			else:
				scores.append(20)
			weights.append(20)

		# Skew score (weight: 15)
		if metrics.skew_angle is not None:
			skew = abs(metrics.skew_angle)
			if skew <= 0.5:
				scores.append(100)
			elif skew <= 1:
				scores.append(90)
			elif skew <= 2:
				scores.append(70)
			elif skew <= 5:
				scores.append(40)
			else:
				scores.append(10)
			weights.append(15)

		# Brightness score (weight: 10)
		if metrics.brightness is not None:
			ideal = 150
			deviation = abs(metrics.brightness - ideal)
			if deviation < 20:
				scores.append(100)
			elif deviation < 40:
				scores.append(80)
			elif deviation < 60:
				scores.append(60)
			else:
				scores.append(max(0, 100 - deviation))
			weights.append(10)

		# Contrast score (weight: 15)
		if metrics.contrast is not None:
			scores.append(min(100, metrics.contrast * 150))
			weights.append(15)

		# Sharpness score (weight: 20)
		if metrics.sharpness is not None:
			scores.append(min(100, metrics.sharpness * 150))
			weights.append(20)

		# Noise score (weight: 10)
		if metrics.noise_level is not None:
			scores.append(max(0, 100 - metrics.noise_level * 200))
			weights.append(10)

		# OCR confidence score (weight: 10)
		if metrics.ocr_confidence is not None:
			scores.append(metrics.ocr_confidence * 100)
			weights.append(10)

		# Calculate weighted average
		if scores and weights:
			metrics.quality_score = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
		else:
			metrics.quality_score = 0.0

		# Determine grade
		if metrics.quality_score >= 90:
			metrics.grade = QualityGrade.EXCELLENT
		elif metrics.quality_score >= 75:
			metrics.grade = QualityGrade.GOOD
		elif metrics.quality_score >= 60:
			metrics.grade = QualityGrade.ACCEPTABLE
		elif metrics.quality_score >= 40:
			metrics.grade = QualityGrade.POOR
		else:
			metrics.grade = QualityGrade.UNACCEPTABLE


# Convenience functions
def assess_document_quality(
	document_path: Path | str,
	ocr_confidence: float | None = None,
	**config: Any,
) -> QualityMetrics:
	"""
	Assess quality of a document image.

	Args:
		document_path: Path to the document image
		ocr_confidence: Optional pre-computed OCR confidence
		**config: Quality threshold configuration

	Returns:
		QualityMetrics with assessment results
	"""
	assessor = QualityAssessor(**config)
	return assessor.assess_image(document_path, ocr_confidence)


def assess_page_quality(
	image_array: np.ndarray,
	dpi: int | None = None,
	ocr_confidence: float | None = None,
	page_number: int | None = None,
	**config: Any,
) -> QualityMetrics:
	"""
	Assess quality of a page image array.

	Args:
		image_array: Page image as numpy array
		dpi: Optional DPI value
		ocr_confidence: Optional OCR confidence
		page_number: Optional page number for issue reporting
		**config: Quality threshold configuration

	Returns:
		QualityMetrics with assessment results
	"""
	assessor = QualityAssessor(**config)
	metrics = assessor.assess_from_array(image_array, dpi, ocr_confidence)

	# Add page number to issues
	if page_number is not None:
		for issue in metrics.issues:
			issue.page_number = page_number

	return metrics
