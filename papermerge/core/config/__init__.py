# (c) Copyright Datacraft, 2026
"""Configuration module for papermerge-core."""
from .features import (
	FeatureConfig,
	get_feature_config,
	is_feature_enabled,
	require_feature,
)

__all__ = [
	'FeatureConfig',
	'get_feature_config',
	'is_feature_enabled',
	'require_feature',
]
