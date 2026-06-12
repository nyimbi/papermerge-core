from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ServiceMetrics(BaseModel):
	model_config = ConfigDict(extra="forbid")

	requests_per_second: float = 0.0
	avg_response_ms: float = 0.0
	error_rate: float = 0.0
	active_connections: int = 0
	queue_depth: int = 0


class ServiceInfo(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str
	name: str
	type: str  # api | worker | scheduler | indexer | cache | database | storage | external
	status: str  # running | stopped | error | starting | stopping | unknown
	host: str = ""
	port: int | None = None
	version: str = "unknown"
	uptime_seconds: int | None = None
	last_heartbeat: str | None = None
	memory_mb: float | None = None
	cpu_percent: float | None = None
	healthy: bool = False
	error_message: str | None = None
	config: dict[str, Any] = Field(default_factory=dict)
	metrics: ServiceMetrics | None = None


class WorkerInfo(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str
	name: str
	queue: str
	status: str  # running | stopped | error | starting | stopping | unknown
	concurrency: int = 1
	active_tasks: int = 0
	completed_tasks: int = 0
	failed_tasks: int = 0
	last_task_at: str | None = None
	current_task: str | None = None
	memory_mb: float | None = None
	cpu_percent: float | None = None
	started_at: str | None = None


class QueueInfo(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str
	pending: int = 0
	active: int = 0
	completed: int = 0
	failed: int = 0
	delayed: int = 0
	priority_pending: dict[str, int] = Field(default_factory=dict)
	oldest_message_age_seconds: float | None = None
	consumers: int = 0


class ScheduledTask(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str
	name: str
	task_name: str
	schedule: str  # cron expression
	category: str = "system"
	enabled: bool = True
	is_running: bool = False
	last_run: str | None = None
	next_run: str | None = None
	last_status: str | None = None  # success | failed | skipped
	last_run_success: bool | None = None
	last_duration_ms: float | None = None
	last_duration_seconds: float | None = None
	timeout_seconds: int | None = None
	error_count: int = 0
	description: str | None = None
	args: dict[str, Any] = Field(default_factory=dict)


class ScheduledTaskUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	enabled: bool | None = None
	schedule: str | None = None
	timeout_seconds: int | None = None


class DatabaseHealth(BaseModel):
	model_config = ConfigDict(extra="forbid")

	connected: bool
	latency_ms: float
	active_connections: int = 0
	max_connections: int = 0
	disk_usage_bytes: int = 0
	disk_total_bytes: int = 0
	replication_lag_ms: float | None = None
	last_backup: str | None = None


class StorageHealth(BaseModel):
	model_config = ConfigDict(extra="forbid")

	available: bool
	latency_ms: float
	used_bytes: int = 0
	total_bytes: int = 0
	objects_count: int = 0


class CacheHealth(BaseModel):
	model_config = ConfigDict(extra="forbid")

	connected: bool
	latency_ms: float
	memory_used_bytes: int = 0
	memory_max_bytes: int = 0
	hit_rate: float = 0.0
	keys_count: int = 0


class SystemHealth(BaseModel):
	model_config = ConfigDict(extra="forbid")

	overall_status: str  # healthy | degraded | unhealthy
	services: list[ServiceInfo] = Field(default_factory=list)
	workers: list[WorkerInfo] = Field(default_factory=list)
	queues: list[QueueInfo] = Field(default_factory=list)
	scheduled_tasks: list[ScheduledTask] = Field(default_factory=list)
	database: DatabaseHealth
	storage: StorageHealth
	cache: CacheHealth


class ServiceConfig(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str
	name: str
	environment: dict[str, str] = Field(default_factory=dict)
	enabled: bool = True
	auto_restart: bool = True
	restart_delay_seconds: int = 5
	max_restarts: int = 3
	healthcheck_interval_seconds: int = 30
	log_level: str = "info"


class ServiceConfigUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	environment: dict[str, str] | None = None
	enabled: bool | None = None
	auto_restart: bool | None = None
	restart_delay_seconds: int | None = None
	max_restarts: int | None = None
	healthcheck_interval_seconds: int | None = None
	log_level: str | None = None


class WorkerConfig(BaseModel):
	model_config = ConfigDict(extra="forbid")

	queue: str
	concurrency: int = 4
	enabled: bool = True
	prefetch_count: int = 4
	task_timeout_seconds: int = 300
	max_retries: int = 3
	retry_delay_seconds: int = 60
	priority_queues: list[str] = Field(default_factory=list)


class WorkerConfigUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	concurrency: int | None = None
	enabled: bool | None = None
	prefetch_count: int | None = None
	task_timeout_seconds: int | None = None
	max_retries: int | None = None
	retry_delay_seconds: int | None = None
	priority_queues: list[str] | None = None


class ActionResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	success: bool
	message: str = ""


class PurgeResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	purged: int


class RetryResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	retried: int
