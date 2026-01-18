# (c) Copyright Datacraft, 2026
"""Base scanner interface and data models."""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator
from uuid import UUID

logger = logging.getLogger(__name__)


class ScannerProtocol(str, Enum):
	"""Supported scanner protocols."""
	ESCL = 'escl'
	SANE = 'sane'
	WIA = 'wia'  # Windows Image Acquisition (future)
	TWAIN = 'twain'  # Legacy (future)


class ScanJobStatus(str, Enum):
	"""Status of a scan job."""
	PENDING = 'pending'
	SCANNING = 'scanning'
	PROCESSING = 'processing'
	COMPLETED = 'completed'
	CANCELLED = 'cancelled'
	FAILED = 'failed'


@dataclass
class ScanOptions:
	"""Options for a scan operation."""
	resolution: int = 300  # DPI
	color_mode: str = 'color'  # color, grayscale, monochrome
	input_source: str = 'platen'  # platen, adf, adf_duplex
	format: str = 'jpeg'  # jpeg, png, tiff, pdf
	quality: int = 85  # JPEG quality (1-100)

	# Scan area (in mm, None = full page)
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
	max_pages: int | None = None

	# Enhancement
	brightness: int = 0  # -100 to 100
	contrast: int = 0  # -100 to 100


@dataclass
class ScanResult:
	"""Result of a scan operation."""
	success: bool
	pages: list[bytes] = field(default_factory=list)
	page_count: int = 0
	format: str = 'jpeg'
	scan_time_ms: float = 0
	errors: list[str] = field(default_factory=list)
	metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanJob:
	"""Represents a scan job."""
	id: str
	scanner_id: str
	user_id: UUID
	status: ScanJobStatus = ScanJobStatus.PENDING
	options: ScanOptions = field(default_factory=ScanOptions)
	pages_scanned: int = 0
	created_at: datetime = field(default_factory=datetime.now)
	started_at: datetime | None = None
	completed_at: datetime | None = None
	result: ScanResult | None = None
	error_message: str | None = None


class Scanner(ABC):
	"""Abstract base class for scanner implementations."""

	protocol: ScannerProtocol

	@property
	@abstractmethod
	def id(self) -> str:
		"""Unique identifier for this scanner."""
		pass

	@property
	@abstractmethod
	def name(self) -> str:
		"""Human-readable name of the scanner."""
		pass

	@property
	@abstractmethod
	def manufacturer(self) -> str:
		"""Scanner manufacturer."""
		pass

	@property
	@abstractmethod
	def model(self) -> str:
		"""Scanner model."""
		pass

	@abstractmethod
	async def is_available(self) -> bool:
		"""Check if scanner is available and ready."""
		pass

	@abstractmethod
	async def get_capabilities(self) -> "ScannerCapabilities":
		"""Get scanner capabilities."""
		pass

	@abstractmethod
	async def scan(self, options: ScanOptions) -> ScanResult:
		"""
		Perform a scan operation.

		Args:
			options: Scan configuration options

		Returns:
			ScanResult with scanned pages
		"""
		pass

	@abstractmethod
	async def scan_stream(
		self,
		options: ScanOptions
	) -> AsyncIterator[tuple[int, bytes]]:
		"""
		Stream scanned pages as they complete.

		Args:
			options: Scan configuration options

		Yields:
			Tuple of (page_number, page_data)
		"""
		pass

	async def scan_preview(self) -> bytes | None:
		"""
		Get a quick preview scan.

		Returns:
			Preview image data or None if not supported
		"""
		# Default: low-res preview scan
		options = ScanOptions(
			resolution=75,
			color_mode='color',
			format='jpeg',
			quality=60,
		)
		result = await self.scan(options)
		if result.success and result.pages:
			return result.pages[0]
		return None

	async def cancel_scan(self) -> bool:
		"""
		Cancel current scan operation.

		Returns:
			True if cancelled successfully
		"""
		return False

	async def get_status(self) -> dict[str, Any]:
		"""
		Get current scanner status.

		Returns:
			Status information dict
		"""
		return {
			'available': await self.is_available(),
			'protocol': self.protocol.value,
		}

	def __repr__(self):
		return f"{self.__class__.__name__}({self.name})"


# Import capabilities here to avoid circular import
from .capabilities import ScannerCapabilities
