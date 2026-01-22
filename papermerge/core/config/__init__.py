# (c) Copyright Datacraft, 2026
"""Configuration module for papermerge-core."""
from .features import (
	FeatureConfig,
	get_feature_config,
	is_feature_enabled,
	require_feature,
)
from .prefect import (
	PrefectSettings,
	get_prefect_settings,
	is_prefect_enabled,
)
from .settings import Settings, get_settings

__all__ = [
	'FeatureConfig',
	'get_feature_config',
	'is_feature_enabled',
	'require_feature',
	'PrefectSettings',
	'get_prefect_settings',
	'is_prefect_enabled',
	'Settings',
	'get_settings',
]
