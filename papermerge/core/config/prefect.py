# (c) Copyright Datacraft, 2026
"""Prefect workflow engine configuration."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PrefectSettings(BaseSettings):
	"""
	Configuration for Prefect workflow engine integration.

	Environment variables are prefixed with PM_PREFECT_.
	"""

	# API connection
	api_url: str = Field(
		default="http://prefect-server:4200/api",
		description="Prefect server API URL",
	)
	api_key: str | None = Field(
		default=None,
		description="Prefect Cloud API key (if using Prefect Cloud)",
	)

	# Work pool configuration
	work_pool: str = Field(
		default="darchiva-workflows",
		description="Name of the Prefect work pool for dArchiva workflows",
	)
	work_queue: str = Field(
		default="default",
		description="Default work queue within the pool",
	)

	# Execution defaults
	default_timeout: int = Field(
		default=3600,
		description="Default task timeout in seconds (1 hour)",
	)
	default_retries: int = Field(
		default=2,
		description="Default number of retries for failed tasks",
	)
	retry_delay_seconds: int = Field(
		default=30,
		description="Delay between retry attempts in seconds",
	)

	# Concurrency limits
	max_concurrent_flows: int = Field(
		default=50,
		description="Maximum concurrent workflow instances",
	)
	max_concurrent_tasks: int = Field(
		default=100,
		description="Maximum concurrent tasks across all flows",
	)

	# Approval timeouts
	approval_timeout_hours: int = Field(
		default=72,
		description="Default timeout for approval tasks in hours",
	)
	escalation_enabled: bool = Field(
		default=True,
		description="Whether to enable automatic escalation on timeout",
	)

	# State synchronization
	state_sync_interval_seconds: int = Field(
		default=5,
		description="How often to sync Prefect state with local DB",
	)
	enable_webhooks: bool = Field(
		default=True,
		description="Enable Prefect webhooks for real-time state updates",
	)

	# Logging and monitoring
	log_level: str = Field(
		default="INFO",
		description="Prefect logging level",
	)
	enable_run_history: bool = Field(
		default=True,
		description="Store full run history for debugging",
	)
	run_history_days: int = Field(
		default=30,
		description="Days to retain run history",
	)

	model_config = SettingsConfigDict(
		env_prefix="PM_PREFECT_",
		extra="forbid",
	)


@lru_cache(maxsize=1)
def get_prefect_settings() -> PrefectSettings:
	"""Get the Prefect configuration singleton."""
	return PrefectSettings()


def is_prefect_enabled() -> bool:
	"""Check if Prefect integration is enabled."""
	from papermerge.core.config.features import is_feature_enabled
	return is_feature_enabled("workflow")
