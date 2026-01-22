# (c) Copyright Datacraft, 2026
"""Scanner management Pydantic schemas."""
from datetime import datetime
from enum import Enum
from typing import Annotated, Any
from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


class ScannerProtocol(str, Enum):
	ESCL = 'escl'
	SANE = 'sane'
	TWAIN = 'twain'
	WIA = 'wia'


class ScannerStatus(str, Enum):
	ONLINE = 'online'
	OFFLINE = 'offline'
	BUSY = 'busy'
	ERROR = 'error'
	MAINTENANCE = 'maintenance'


class ScanJobStatus(str, Enum):
	PENDING = 'pending'
	SCANNING = 'scanning'
	PROCESSING = 'processing'
	COMPLETED = 'completed'
	CANCELLED = 'cancelled'
	FAILED = 'failed'


class ColorMode(str, Enum):
	COLOR = 'color'
	GRAYSCALE = 'grayscale'
	MONOCHROME = 'monochrome'


class InputSource(str, Enum):
	PLATEN = 'platen'
	ADF = 'adf'
	ADF_DUPLEX = 'adf_duplex'


class ImageFormat(str, Enum):
	JPEG = 'jpeg'
	PNG = 'png'
	TIFF = 'tiff'
	PDF = 'pdf'


# === Scanner Device Schemas ===

class ScannerCapabilitiesResponse(BaseModel):
	model_config = ConfigDict(extra='forbid')

	platen: bool = True
	adf_present: bool = False
	adf_duplex: bool = False
	adf_capacity: int = 0
	resolutions: list[int] = Field(default_factory=lambda: [150, 300, 600])
	color_modes: list[ColorMode] = Field(default_factory=lambda: [ColorMode.COLOR, ColorMode.GRAYSCALE])
	formats: list[ImageFormat] = Field(default_factory=lambda: [ImageFormat.JPEG, ImageFormat.PNG])
	max_width_mm: float = 215.9
	max_height_mm: float = 355.6
	auto_crop: bool = False
	auto_deskew: bool = False
	blank_page_removal: bool = False
	brightness_control: bool = True
	contrast_control: bool = True


class DiscoveredScannerResponse(BaseModel):
	model_config = ConfigDict(extra='forbid')

	name: str
	host: str
	port: int
	protocol: ScannerProtocol
	uuid: str | None = None
	manufacturer: str | None = None
	model: str | None = None
	serial: str | None = None
	root_url: str | None = None
	discovered_at: datetime


class ScannerBase(BaseModel):
	model_config = ConfigDict(extra='forbid')

	name: str = Field(..., min_length=1, max_length=255)
	protocol: ScannerProtocol
	connection_uri: str = Field(..., min_length=1, max_length=500)
	location_id: str | None = None
	is_default: bool = False
	is_active: bool = True
	notes: str | None = None


class ScannerCreate(ScannerBase):
	pass


class ScannerUpdate(BaseModel):
	model_config = ConfigDict(extra='forbid')

	name: str | None = None
	location_id: str | None = None
	is_default: bool | None = None
	is_active: bool | None = None
	notes: str | None = None


class ScannerResponse(ScannerBase):
	id: str
	tenant_id: str
	manufacturer: str | None = None
	model: str | None = None
	serial_number: str | None = None
	firmware_version: str | None = None
	status: ScannerStatus = ScannerStatus.OFFLINE
	last_seen_at: datetime | None = None
	total_pages_scanned: int = 0
	capabilities: ScannerCapabilitiesResponse | None = None
	has_api_key: bool = False
	created_at: datetime
	updated_at: datetime


class ScannerApiKeyResponse(BaseModel):
	model_config = ConfigDict(extra='forbid')

	scanner_id: str
	api_key: str
	message: str = "Store this key securely. It will not be shown again."


class ScannerStatusResponse(BaseModel):
	model_config = ConfigDict(extra='forbid')

	scanner_id: str
	status: ScannerStatus
	available: bool
	state: str | None = None
	adf_state: str | None = None
	active_jobs: int = 0
	error: str | None = None
	last_checked: datetime


# === Scan Options & Jobs ===

class ScanOptionsBase(BaseModel):
	model_config = ConfigDict(extra='forbid')

	resolution: int = Field(default=300, ge=75, le=2400)
	color_mode: ColorMode = ColorMode.COLOR
	input_source: InputSource = InputSource.PLATEN
	format: ImageFormat = ImageFormat.JPEG
	quality: int = Field(default=85, ge=1, le=100)

	# Scan area (mm, None = full page)
	x_offset: float | None = None
	y_offset: float | None = None
	width: float | None = None
	height: float | None = None

	# Paper handling
	duplex: bool = False
	auto_crop: bool = False
	auto_deskew: bool = False
	blank_page_removal: bool = False

	# Multi-page
	batch_mode: bool = False
	max_pages: int | None = Field(default=None, ge=1, le=1000)

	# Enhancement
	brightness: int = Field(default=0, ge=-100, le=100)
	contrast: int = Field(default=0, ge=-100, le=100)


class ScanJobCreate(BaseModel):
	model_config = ConfigDict(extra='forbid')

	scanner_id: str
	options: ScanOptionsBase = Field(default_factory=ScanOptionsBase)
	project_id: str | None = None
	batch_id: str | None = None
	destination_folder_id: str | None = None
	auto_process: bool = True  # Run OCR after scan


class ScanJobResponse(BaseModel):
	model_config = ConfigDict(extra='forbid')

	id: str
	scanner_id: str
	user_id: str
	status: ScanJobStatus
	options: ScanOptionsBase
	pages_scanned: int = 0
	project_id: str | None = None
	batch_id: str | None = None
	destination_folder_id: str | None = None
	error_message: str | None = None
	created_at: datetime
	started_at: datetime | None = None
	completed_at: datetime | None = None


class ScanJobResultResponse(BaseModel):
	model_config = ConfigDict(extra='forbid')

	job_id: str
	success: bool
	pages_scanned: int
	format: ImageFormat
	scan_time_ms: float
	document_ids: list[str] = Field(default_factory=list)
	errors: list[str] = Field(default_factory=list)


# === Scanner Profiles ===

class ScanProfileBase(BaseModel):
	model_config = ConfigDict(extra='forbid')

	name: str = Field(..., min_length=1, max_length=100)
	description: str | None = None
	is_default: bool = False
	options: ScanOptionsBase


class ScanProfileCreate(ScanProfileBase):
	pass


class ScanProfileUpdate(BaseModel):
	model_config = ConfigDict(extra='forbid')

	name: str | None = None
	description: str | None = None
	is_default: bool | None = None
	options: ScanOptionsBase | None = None


class ScanProfileResponse(ScanProfileBase):
	id: str
	tenant_id: str
	created_by_id: str
	created_at: datetime
	updated_at: datetime


# === Scanner Settings ===

class GlobalScannerSettingsUpdate(BaseModel):
	model_config = ConfigDict(extra='forbid')

	auto_discovery_enabled: bool | None = None
	discovery_interval_seconds: int | None = Field(default=None, ge=30, le=3600)
	default_profile_id: str | None = None
	auto_process_scans: bool | None = None
	default_destination_folder_id: str | None = None


class GlobalScannerSettingsResponse(BaseModel):
	model_config = ConfigDict(extra='forbid')

	auto_discovery_enabled: bool = True
	discovery_interval_seconds: int = 300
	default_profile_id: str | None = None
	auto_process_scans: bool = True
	default_destination_folder_id: str | None = None


# === Analytics ===

class ScannerUsageStats(BaseModel):
	model_config = ConfigDict(extra='forbid')

	scanner_id: str
	scanner_name: str
	total_jobs: int
	total_pages: int
	successful_jobs: int
	failed_jobs: int
	average_pages_per_job: float
	average_scan_time_ms: float
	uptime_percentage: float


class ScannerDashboard(BaseModel):
	model_config = ConfigDict(extra='forbid')

	total_scanners: int
	online_scanners: int
	offline_scanners: int
	busy_scanners: int
	total_pages_today: int
	total_jobs_today: int
	scanners: list[ScannerResponse]
	recent_jobs: list[ScanJobResponse]
	usage_stats: list[ScannerUsageStats]
