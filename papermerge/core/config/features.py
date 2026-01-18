# (c) Copyright Datacraft, 2026
"""
Global feature configuration.

Combines system-level feature settings with tenant-specific overrides.
"""
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class FeatureConfig(BaseSettings):
	"""
	System-level feature configuration.

	These settings control global feature availability.
	Tenant-specific overrides are handled by the tenancy module.
	"""

	# OCR Features
	ocr_enabled: bool = True
	ocr_paddle_enabled: bool = False
	ocr_qwen_vl_enabled: bool = False
	ocr_default_engine: str = "tesseract"  # tesseract | paddle | qwen_vl | hybrid

	# NLP Features
	nlp_enabled: bool = False
	nlp_spacy_model: str = "en_core_web_sm"  # en_core_web_sm | en_core_web_trf

	# Search Features
	search_fts_enabled: bool = True
	search_semantic_enabled: bool = False
	search_elasticsearch_enabled: bool = False
	search_meilisearch_enabled: bool = False

	# Workflow Features
	workflow_enabled: bool = True
	workflow_advanced_nodes: bool = False

	# Security Features
	encryption_enabled: bool = False
	mfa_enabled: bool = False
	mfa_totp_enabled: bool = True
	mfa_sms_enabled: bool = False
	passkeys_enabled: bool = False
	abac_enabled: bool = False
	rebac_enabled: bool = False

	# Storage Features
	storage_tiering_enabled: bool = False
	storage_hot_days: int = 30  # Days before moving to cold
	storage_cold_days: int = 365  # Days before moving to archive

	# Scanner Features
	scanner_enabled: bool = False
	scanner_escl_enabled: bool = False
	scanner_sane_enabled: bool = False
	scanner_discovery_enabled: bool = True

	# Quality Features
	quality_assessment_enabled: bool = False
	quality_auto_reject: bool = False
	quality_min_dpi: int = 200

	# Batch/Provenance Features
	batch_enabled: bool = True
	provenance_enabled: bool = True
	provenance_hash_algorithm: str = "sha256"

	# Billing Features
	billing_enabled: bool = False
	billing_metering_enabled: bool = False

	# Integration Features
	email_import_enabled: bool = False
	email_imap_enabled: bool = False
	email_graph_enabled: bool = False  # Microsoft Graph API

	# AI Features
	ai_enabled: bool = False
	ai_classification_enabled: bool = False
	ai_summarization_enabled: bool = False
	ai_chat_enabled: bool = False

	# Multi-tenancy
	multi_tenant_enabled: bool = False
	tenant_schema_isolation: bool = True

	model_config = SettingsConfigDict(env_prefix='pm_feature_')


@lru_cache(maxsize=1)
def get_feature_config() -> FeatureConfig:
	"""Get the global feature configuration."""
	return FeatureConfig()


def is_feature_enabled(feature_name: str) -> bool:
	"""
	Check if a feature is enabled globally.

	This only checks system-level configuration.
	For tenant-aware checks, use tenancy.features.feature_enabled().
	"""
	config = get_feature_config()
	attr_name = f"{feature_name.replace('.', '_')}_enabled"

	# Try exact match first
	if hasattr(config, attr_name):
		return getattr(config, attr_name)

	# Try without _enabled suffix
	if hasattr(config, feature_name.replace('.', '_')):
		return getattr(config, feature_name.replace('.', '_'))

	logger.warning(f"Unknown feature: {feature_name}")
	return False


def require_feature(feature_name: str) -> bool:
	"""
	Assert that a feature is enabled, raising if not.

	Useful as a guard at the start of feature-specific code paths.
	"""
	if not is_feature_enabled(feature_name):
		from fastapi import HTTPException
		raise HTTPException(
			status_code=403,
			detail=f"Feature '{feature_name}' is not enabled",
		)
	return True


# Feature dependencies - if feature A requires feature B
FEATURE_DEPENDENCIES: dict[str, list[str]] = {
	"search.semantic": ["search.fts"],
	"ocr.paddle": ["ocr"],
	"ocr.qwen_vl": ["ocr", "ai"],
	"nlp.extraction": ["ocr"],
	"workflow.advanced": ["workflow"],
	"mfa.totp": ["mfa"],
	"mfa.sms": ["mfa"],
	"scanner.escl": ["scanner"],
	"scanner.sane": ["scanner"],
	"ai.classification": ["ai", "nlp"],
	"ai.summarization": ["ai"],
	"ai.chat": ["ai"],
}


def get_feature_dependencies(feature_name: str) -> list[str]:
	"""Get list of features that must be enabled for the given feature."""
	return FEATURE_DEPENDENCIES.get(feature_name, [])


def validate_feature_dependencies() -> list[str]:
	"""
	Validate that all feature dependencies are satisfied.

	Returns list of error messages for unsatisfied dependencies.
	"""
	errors = []
	config = get_feature_config()

	for feature, deps in FEATURE_DEPENDENCIES.items():
		if is_feature_enabled(feature):
			for dep in deps:
				if not is_feature_enabled(dep):
					errors.append(
						f"Feature '{feature}' requires '{dep}' to be enabled"
					)

	return errors


@dataclass
class FeatureSet:
	"""
	Represents a set of enabled features.

	Useful for serializing feature state to the frontend.
	"""
	features: dict[str, bool] = field(default_factory=dict)

	@classmethod
	def from_config(cls) -> "FeatureSet":
		"""Create FeatureSet from current configuration."""
		config = get_feature_config()
		features = {}

		for attr in dir(config):
			if attr.endswith("_enabled"):
				feature_name = attr[:-8].replace("_", ".")
				features[feature_name] = getattr(config, attr)

		return cls(features=features)

	def is_enabled(self, feature: str) -> bool:
		"""Check if a feature is enabled."""
		return self.features.get(feature, False)

	def to_dict(self) -> dict[str, bool]:
		"""Convert to dictionary."""
		return self.features.copy()


class FeatureResponse(BaseModel):
	"""API response for feature configuration."""
	features: dict[str, bool]
	tier: str = "free"
	limits: dict[str, Any] = {}


def get_feature_response(
	tier: str = "free",
	limits: dict[str, Any] | None = None,
) -> FeatureResponse:
	"""Get feature configuration for API response."""
	feature_set = FeatureSet.from_config()
	return FeatureResponse(
		features=feature_set.to_dict(),
		tier=tier,
		limits=limits or {},
	)
