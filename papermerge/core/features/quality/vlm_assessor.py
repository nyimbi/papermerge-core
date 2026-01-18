# (c) Copyright Datacraft, 2026
"""
VLM-powered document quality assessment using Qwen-VL.

Provides intelligent quality analysis using vision-language models
for deeper understanding of document content and issues.
"""
import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .assessment import QualityMetrics, QualityIssue, QualityGrade

logger = logging.getLogger(__name__)


def _log_vlm_request(model: str) -> str:
	return f"VLM quality assessment using {model}"


@dataclass
class VLMQualityConfig:
	"""Configuration for VLM-based quality assessment."""
	ollama_base_url: str = "http://localhost:11434"
	model: str = "qwen2.5-vl:7b"  # or "qwen3-vl" when available
	timeout: float = 120.0
	temperature: float = 0.3
	max_tokens: int = 2048


QUALITY_ASSESSMENT_PROMPT = """Analyze this scanned document image for quality issues. Provide your assessment as JSON.

Evaluate the following aspects:
1. **Readability**: Is text clearly legible? Any blurred or unclear sections?
2. **Scan Quality**: Resolution, brightness, contrast, noise levels
3. **Alignment**: Is the document straight or skewed? Any rotation issues?
4. **Content Integrity**: Are all parts visible? Any cut-off edges, missing corners?
5. **Artifacts**: Smudges, stains, shadows, finger marks, paper damage?
6. **Document Type**: What type of document is this? (invoice, letter, form, contract, etc.)

Respond with this exact JSON structure:
{
  "document_type": "string describing document type",
  "readability_score": 0-100,
  "scan_quality_score": 0-100,
  "alignment_score": 0-100,
  "content_integrity_score": 0-100,
  "overall_quality_score": 0-100,
  "quality_grade": "excellent|good|acceptable|poor|unacceptable",
  "is_blank": true|false,
  "has_handwriting": true|false,
  "has_stamps_or_signatures": true|false,
  "language_detected": "language code or 'unknown'",
  "issues": [
    {
      "type": "skew|blur|dark|bright|noise|cutoff|artifact|smudge|other",
      "severity": "info|warning|error|critical",
      "description": "detailed description of the issue",
      "location": "top|bottom|left|right|center|all|specific area description",
      "auto_fixable": true|false
    }
  ],
  "recommendations": ["list of specific recommendations to improve quality"],
  "summary": "2-3 sentence summary of document quality"
}"""


class VLMQualityAssessor:
	"""
	Uses Qwen-VL to perform intelligent document quality assessment.

	Provides richer analysis than pure image processing by understanding
	document content and context.
	"""

	def __init__(self, config: VLMQualityConfig | None = None):
		self.config = config or VLMQualityConfig()
		self._base_url = self.config.ollama_base_url.rstrip("/")

	async def assess_image(
		self,
		image_path: Path | str,
		include_traditional: bool = True,
	) -> dict[str, Any]:
		"""
		Assess document quality using VLM analysis.

		Args:
			image_path: Path to the document image
			include_traditional: Also run traditional CV analysis

		Returns:
			Complete quality assessment including VLM insights
		"""
		path = Path(image_path)
		if not path.exists():
			raise FileNotFoundError(f"Image not found: {path}")

		# Read and encode image
		image_data = path.read_bytes()
		image_base64 = base64.b64encode(image_data).decode("utf-8")

		# Determine mime type
		suffix = path.suffix.lower()
		mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".tiff": "image/tiff", ".tif": "image/tiff"}
		mime_type = mime_map.get(suffix, "image/jpeg")

		# Call VLM
		vlm_result = await self._call_vlm(image_base64, mime_type)

		# Optionally combine with traditional assessment
		if include_traditional:
			from .assessment import assess_document_quality
			traditional = assess_document_quality(path)
			vlm_result["traditional_metrics"] = {
				"resolution_dpi": traditional.resolution_dpi,
				"skew_angle": traditional.skew_angle,
				"brightness": traditional.brightness,
				"contrast": traditional.contrast,
				"sharpness": traditional.sharpness,
				"noise_level": traditional.noise_level,
				"traditional_score": traditional.quality_score,
				"traditional_grade": traditional.grade.value,
			}
			# Blend scores
			if vlm_result.get("overall_quality_score") and traditional.quality_score:
				vlm_result["blended_score"] = (
					vlm_result["overall_quality_score"] * 0.6 +
					traditional.quality_score * 0.4
				)

		return vlm_result

	async def assess_from_bytes(
		self,
		image_bytes: bytes,
		mime_type: str = "image/jpeg",
	) -> dict[str, Any]:
		"""Assess quality from image bytes."""
		image_base64 = base64.b64encode(image_bytes).decode("utf-8")
		return await self._call_vlm(image_base64, mime_type)

	async def _call_vlm(
		self,
		image_base64: str,
		mime_type: str,
	) -> dict[str, Any]:
		"""Call Ollama VLM API with the image."""
		logger.info(_log_vlm_request(self.config.model))

		# Construct messages with image
		messages = [
			{
				"role": "user",
				"content": QUALITY_ASSESSMENT_PROMPT,
				"images": [image_base64],
			}
		]

		payload = {
			"model": self.config.model,
			"messages": messages,
			"stream": False,
			"format": "json",
			"options": {
				"temperature": self.config.temperature,
				"num_predict": self.config.max_tokens,
			},
		}

		url = f"{self._base_url}/api/chat"

		try:
			async with httpx.AsyncClient(timeout=self.config.timeout) as client:
				response = await client.post(url, json=payload)
				response.raise_for_status()
				data = response.json()

			content = data["message"]["content"]
			# Parse JSON from response
			if content.startswith("```"):
				lines = content.split("\n")
				content = "\n".join(lines[1:-1])

			result = json.loads(content)
			result["model"] = self.config.model
			result["assessment_method"] = "vlm"
			return result

		except httpx.TimeoutException:
			logger.error("VLM request timed out")
			return self._fallback_result("VLM request timed out")
		except json.JSONDecodeError as e:
			logger.error(f"Failed to parse VLM response: {e}")
			return self._fallback_result(f"Invalid VLM response format: {e}")
		except Exception as e:
			logger.error(f"VLM assessment failed: {e}")
			return self._fallback_result(str(e))

	def _fallback_result(self, error: str) -> dict[str, Any]:
		"""Return a fallback result when VLM fails."""
		return {
			"assessment_method": "fallback",
			"error": error,
			"overall_quality_score": None,
			"quality_grade": None,
			"issues": [],
			"recommendations": ["Unable to perform VLM assessment. Use traditional CV-based assessment."],
			"summary": "VLM assessment failed. Manual review recommended.",
		}

	async def health_check(self) -> bool:
		"""Check if VLM service is available."""
		try:
			async with httpx.AsyncClient(timeout=5.0) as client:
				response = await client.get(f"{self._base_url}/api/tags")
				if response.status_code != 200:
					return False
				data = response.json()
				models = [m["name"] for m in data.get("models", [])]
				# Check if our model is available
				return any(self.config.model in m for m in models)
		except Exception as e:
			logger.error(f"VLM health check failed: {e}")
			return False


@dataclass
class HybridQualityResult:
	"""Combined result from traditional and VLM assessment."""
	# Traditional metrics
	resolution_dpi: int | None = None
	skew_angle: float | None = None
	brightness: float | None = None
	contrast: float | None = None
	sharpness: float | None = None
	noise_level: float | None = None

	# VLM insights
	document_type: str | None = None
	readability_score: int | None = None
	has_handwriting: bool = False
	has_stamps_or_signatures: bool = False
	language_detected: str | None = None

	# Scores
	traditional_score: float = 0.0
	vlm_score: float = 0.0
	blended_score: float = 0.0

	# Grade and issues
	grade: QualityGrade = QualityGrade.UNACCEPTABLE
	issues: list[dict[str, Any]] = field(default_factory=list)
	recommendations: list[str] = field(default_factory=list)
	summary: str = ""


async def assess_with_vlm(
	image_path: Path | str,
	config: VLMQualityConfig | None = None,
) -> HybridQualityResult:
	"""
	Perform hybrid quality assessment using both VLM and traditional methods.

	Args:
		image_path: Path to document image
		config: Optional VLM configuration

	Returns:
		HybridQualityResult with combined insights
	"""
	assessor = VLMQualityAssessor(config)
	vlm_result = await assessor.assess_image(image_path, include_traditional=True)

	# Build hybrid result
	result = HybridQualityResult()

	# Traditional metrics
	if "traditional_metrics" in vlm_result:
		tm = vlm_result["traditional_metrics"]
		result.resolution_dpi = tm.get("resolution_dpi")
		result.skew_angle = tm.get("skew_angle")
		result.brightness = tm.get("brightness")
		result.contrast = tm.get("contrast")
		result.sharpness = tm.get("sharpness")
		result.noise_level = tm.get("noise_level")
		result.traditional_score = tm.get("traditional_score", 0.0)

	# VLM insights
	result.document_type = vlm_result.get("document_type")
	result.readability_score = vlm_result.get("readability_score")
	result.has_handwriting = vlm_result.get("has_handwriting", False)
	result.has_stamps_or_signatures = vlm_result.get("has_stamps_or_signatures", False)
	result.language_detected = vlm_result.get("language_detected")
	result.vlm_score = vlm_result.get("overall_quality_score", 0.0) or 0.0

	# Blended score
	result.blended_score = vlm_result.get("blended_score", result.vlm_score)

	# Determine grade from blended score
	if result.blended_score >= 90:
		result.grade = QualityGrade.EXCELLENT
	elif result.blended_score >= 75:
		result.grade = QualityGrade.GOOD
	elif result.blended_score >= 60:
		result.grade = QualityGrade.ACCEPTABLE
	elif result.blended_score >= 40:
		result.grade = QualityGrade.POOR
	else:
		result.grade = QualityGrade.UNACCEPTABLE

	# Issues and recommendations
	result.issues = vlm_result.get("issues", [])
	result.recommendations = vlm_result.get("recommendations", [])
	result.summary = vlm_result.get("summary", "")

	return result
