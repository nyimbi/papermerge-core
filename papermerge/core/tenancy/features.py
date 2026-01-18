# (c) Copyright Datacraft, 2026
"""
Feature flags for per-tenant feature management.

Provides a flexible system for enabling/disabling features
on a per-tenant basis, with support for percentage rollouts,
A/B testing, and gradual feature releases.
"""
import logging
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class FeatureState(str, Enum):
	"""Feature availability state."""
	ENABLED = "enabled"
	DISABLED = "disabled"
	PERCENTAGE = "percentage"  # Enabled for a percentage of users
	ALLOWLIST = "allowlist"  # Enabled for specific tenants
	BLOCKLIST = "blocklist"  # Disabled for specific tenants


@dataclass
class FeatureDefinition:
	"""Definition of a feature flag."""
	name: str
	description: str = ""
	default_enabled: bool = False
	state: FeatureState = FeatureState.DISABLED
	percentage: int = 0  # 0-100, used when state is PERCENTAGE
	allowlist: set[str] = field(default_factory=set)  # Tenant slugs
	blocklist: set[str] = field(default_factory=set)  # Tenant slugs
	metadata: dict[str, Any] = field(default_factory=dict)


# Core feature definitions
FEATURES: dict[str, FeatureDefinition] = {
	# Document processing features
	"ocr": FeatureDefinition(
		name="ocr",
		description="Optical Character Recognition",
		default_enabled=True,
		state=FeatureState.ENABLED,
	),
	"ocr.paddle": FeatureDefinition(
		name="ocr.paddle",
		description="PaddleOCR engine",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"ocr.qwen_vl": FeatureDefinition(
		name="ocr.qwen_vl",
		description="Qwen VL OCR (Ollama)",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"nlp.extraction": FeatureDefinition(
		name="nlp.extraction",
		description="SpaCy NLP entity extraction",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),

	# Search features
	"search.semantic": FeatureDefinition(
		name="search.semantic",
		description="Semantic/vector search",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"search.elasticsearch": FeatureDefinition(
		name="search.elasticsearch",
		description="Elasticsearch backend",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"search.meilisearch": FeatureDefinition(
		name="search.meilisearch",
		description="Meilisearch backend",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),

	# Workflow features
	"workflows": FeatureDefinition(
		name="workflows",
		description="Visual workflow designer",
		default_enabled=True,
		state=FeatureState.ENABLED,
	),
	"workflows.advanced": FeatureDefinition(
		name="workflows.advanced",
		description="Advanced workflow nodes (AI, conditions)",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),

	# Security features
	"encryption": FeatureDefinition(
		name="encryption",
		description="Document encryption at rest",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"mfa": FeatureDefinition(
		name="mfa",
		description="Multi-factor authentication",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"passkeys": FeatureDefinition(
		name="passkeys",
		description="WebAuthn/FIDO2 passkeys",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"abac": FeatureDefinition(
		name="abac",
		description="Attribute-based access control",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"rebac": FeatureDefinition(
		name="rebac",
		description="Relationship-based access control",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),

	# Storage features
	"storage.tiering": FeatureDefinition(
		name="storage.tiering",
		description="Hot/cold/archive storage tiers",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"storage.linode": FeatureDefinition(
		name="storage.linode",
		description="Linode Object Storage",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),

	# Scanner features
	"scanner": FeatureDefinition(
		name="scanner",
		description="Direct scanner integration",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"scanner.escl": FeatureDefinition(
		name="scanner.escl",
		description="eSCL/AirScan protocol",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"scanner.sane": FeatureDefinition(
		name="scanner.sane",
		description="SANE scanner backend",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),

	# Quality features
	"quality.assessment": FeatureDefinition(
		name="quality.assessment",
		description="Document quality scoring",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),

	# Batch/provenance features
	"batches": FeatureDefinition(
		name="batches",
		description="Batch document processing",
		default_enabled=True,
		state=FeatureState.ENABLED,
	),
	"provenance": FeatureDefinition(
		name="provenance",
		description="Document provenance tracking",
		default_enabled=True,
		state=FeatureState.ENABLED,
	),

	# Billing features
	"billing": FeatureDefinition(
		name="billing",
		description="Usage billing and metering",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),

	# Integration features
	"email.import": FeatureDefinition(
		name="email.import",
		description="Email document import",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),

	# AI features
	"ai.classification": FeatureDefinition(
		name="ai.classification",
		description="AI document classification",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
	"ai.summarization": FeatureDefinition(
		name="ai.summarization",
		description="AI document summarization",
		default_enabled=False,
		state=FeatureState.DISABLED,
	),
}


@dataclass
class FeatureFlags:
	"""
	Feature flag resolver for a specific tenant.

	Evaluates feature availability based on tenant configuration,
	global feature state, and rollout settings.
	"""
	tenant_id: UUID | None
	tenant_slug: str | None
	tenant_features: dict[str, bool] | None = None
	plan: str | None = None

	def is_enabled(self, feature_name: str) -> bool:
		"""
		Check if a feature is enabled for this tenant.

		Resolution order:
		1. Tenant-specific override (from database)
		2. Blocklist check
		3. Allowlist check
		4. Percentage rollout
		5. Default state
		"""
		# Get feature definition
		feature = FEATURES.get(feature_name)
		if feature is None:
			logger.warning(f"Unknown feature: {feature_name}")
			return False

		# 1. Check tenant-specific override
		if self.tenant_features and feature_name in self.tenant_features:
			return self.tenant_features[feature_name]

		# 2. Check blocklist
		if (
			feature.state == FeatureState.BLOCKLIST
			and self.tenant_slug in feature.blocklist
		):
			return False

		# 3. Check allowlist
		if feature.state == FeatureState.ALLOWLIST:
			return self.tenant_slug in feature.allowlist

		# 4. Check percentage rollout
		if feature.state == FeatureState.PERCENTAGE:
			return self._is_in_percentage(feature_name, feature.percentage)

		# 5. Check global state
		if feature.state == FeatureState.ENABLED:
			return True
		if feature.state == FeatureState.DISABLED:
			return feature.default_enabled

		return feature.default_enabled

	def _is_in_percentage(self, feature_name: str, percentage: int) -> bool:
		"""
		Determine if tenant falls within the percentage rollout.

		Uses consistent hashing so the same tenant always gets
		the same result for a given feature.
		"""
		if self.tenant_id is None:
			return False

		# Create a hash from tenant ID and feature name
		hash_input = f"{self.tenant_id}:{feature_name}"
		hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)

		# Map to 0-99
		bucket = hash_value % 100

		return bucket < percentage

	def get_all_features(self) -> dict[str, bool]:
		"""Get all feature flags for this tenant."""
		return {name: self.is_enabled(name) for name in FEATURES}

	def get_enabled_features(self) -> list[str]:
		"""Get list of enabled feature names."""
		return [name for name, enabled in self.get_all_features().items() if enabled]

	def get_disabled_features(self) -> list[str]:
		"""Get list of disabled feature names."""
		return [name for name, enabled in self.get_all_features().items() if not enabled]


def get_feature_flags(
	tenant_id: UUID | None = None,
	tenant_slug: str | None = None,
	tenant_features: dict[str, bool] | None = None,
	plan: str | None = None,
) -> FeatureFlags:
	"""
	Create a FeatureFlags instance for the given tenant.

	If no tenant info is provided, uses the current tenant context.
	"""
	if tenant_id is None and tenant_slug is None:
		from .context import get_tenant_context
		ctx = get_tenant_context()
		if ctx:
			tenant_id = ctx.tenant_id
			tenant_slug = ctx.tenant_slug
			tenant_features = ctx.features
			plan = ctx.plan

	return FeatureFlags(
		tenant_id=tenant_id,
		tenant_slug=tenant_slug,
		tenant_features=tenant_features,
		plan=plan,
	)


def require_feature(feature_name: str) -> bool:
	"""
	Check if a feature is required/enabled, raising if not.

	Use as a guard in code paths that require specific features.
	"""
	flags = get_feature_flags()
	if not flags.is_enabled(feature_name):
		from fastapi import HTTPException
		raise HTTPException(
			status_code=403,
			detail=f"Feature '{feature_name}' is not enabled for this tenant",
		)
	return True


def feature_enabled(feature_name: str) -> bool:
	"""Quick check if a feature is enabled for current tenant."""
	return get_feature_flags().is_enabled(feature_name)


# Plan-based feature bundles
PLAN_FEATURES: dict[str, list[str]] = {
	"free": [
		"ocr",
		"workflows",
		"batches",
		"provenance",
	],
	"starter": [
		"ocr",
		"ocr.paddle",
		"workflows",
		"batches",
		"provenance",
		"mfa",
		"search.semantic",
	],
	"professional": [
		"ocr",
		"ocr.paddle",
		"ocr.qwen_vl",
		"nlp.extraction",
		"workflows",
		"workflows.advanced",
		"batches",
		"provenance",
		"mfa",
		"passkeys",
		"search.semantic",
		"encryption",
		"scanner",
		"scanner.escl",
		"quality.assessment",
		"email.import",
		"ai.classification",
	],
	"enterprise": [
		# All features
		*FEATURES.keys(),
	],
}


def get_plan_features(plan: str) -> list[str]:
	"""Get list of features included in a plan."""
	return PLAN_FEATURES.get(plan.lower(), PLAN_FEATURES["free"])
