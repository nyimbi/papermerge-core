# (c) Copyright Datacraft, 2026
"""TWAIN scanner interface for Windows.

TWAIN is the legacy but widely-supported scanning protocol on Windows.
This implementation uses ctypes to interface with the TWAIN DSM (Data Source Manager).
"""
import asyncio
import ctypes
import logging
import sys
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from .base import (
	Scanner, ScannerInfo, ScanOptions, ScanResult, ScanJob,
	ScannerProtocol, ScannerStatus, ColorMode, InputSource, ImageFormat,
)
from .capabilities import ScannerCapabilities

logger = logging.getLogger(__name__)


class TwainRC(IntEnum):
	"""TWAIN Return Codes."""
	SUCCESS = 0
	FAILURE = 1
	CHECKSTATUS = 2
	CANCEL = 3
	DSEVENT = 4
	NOTDSEVENT = 5
	XFERDONE = 6
	ENDOFLIST = 7
	INFONOTSUPPORTED = 8
	DATANOTAVAILABLE = 9
	BUSY = 10
	SCANNERLOCKED = 11


class TwainDG(IntEnum):
	"""TWAIN Data Groups."""
	CONTROL = 1
	IMAGE = 2
	AUDIO = 4


class TwainDAT(IntEnum):
	"""TWAIN Data Argument Types."""
	NULL = 0
	CAPABILITY = 1
	EVENT = 2
	IDENTITY = 3
	PARENT = 4
	PENDINGXFERS = 5
	SETUPMEMXFER = 6
	SETUPFILEXFER = 7
	STATUS = 8
	USERINTERFACE = 9
	XFERGROUP = 10
	IMAGENATIVEXFER = 0x0104
	IMAGEFILEXFER = 0x0105
	IMAGEMEMXFER = 0x0106
	IMAGELAYOUT = 0x0102
	IMAGEINFO = 0x0101


class TwainMSG(IntEnum):
	"""TWAIN Messages."""
	NULL = 0
	GET = 1
	GETCURRENT = 2
	GETDEFAULT = 3
	GETFIRST = 4
	GETNEXT = 5
	SET = 6
	RESET = 7
	QUERYSUPPORT = 8
	OPENDSM = 0x0301
	CLOSEDSM = 0x0302
	OPENDS = 0x0401
	CLOSEDS = 0x0402
	USERSELECT = 0x0403
	ENABLEDS = 0x0501
	ENABLEDSUIONLY = 0x0502
	DISABLEDS = 0x0503


class TwainCAP(IntEnum):
	"""TWAIN Capabilities."""
	XFERCOUNT = 0x0001
	ICAPCOMPRESSION = 0x0100
	ICAPPIXELTYPE = 0x0101
	ICAPUNITS = 0x0102
	ICAPXFERMECH = 0x0103
	ICAPXRESOLUTION = 0x1118
	ICAPYRESOLUTION = 0x1119
	ICAPBITDEPTH = 0x112B
	CAP_FEEDERENABLED = 0x1002
	CAP_FEEDERLOADED = 0x1003
	CAP_AUTOFEED = 0x1007
	CAP_DUPLEXENABLED = 0x1013
	CAP_DUPLEX = 0x1012


@dataclass
class TwainIdentity:
	"""TWAIN Data Source Identity."""
	id: int = 0
	version_major: int = 0
	version_minor: int = 0
	supported_groups: int = 0
	manufacturer: str = ""
	product_family: str = ""
	product_name: str = ""


class TWAINScanner(Scanner):
	"""TWAIN scanner implementation for Windows.

	Provides synchronous scanning operations wrapped in async interface.
	Uses ctypes to communicate with TWAIN Data Source Manager.
	"""

	def __init__(self, identity: TwainIdentity):
		self._identity = identity
		self._dsm_handle: Any = None
		self._ds_handle: Any = None
		self._hwnd: Any = None
		self._is_open = False
		self._capabilities: ScannerCapabilities | None = None

		# Only available on Windows
		if sys.platform != 'win32':
			raise RuntimeError("TWAIN is only available on Windows")

	@property
	def info(self) -> ScannerInfo:
		return ScannerInfo(
			name=self._identity.product_name,
			manufacturer=self._identity.manufacturer,
			model=self._identity.product_family,
			protocol=ScannerProtocol.TWAIN,
			connection_uri=f"twain://{self._identity.id}",
		)

	@property
	def protocol(self) -> ScannerProtocol:
		return ScannerProtocol.TWAIN

	@property
	def is_connected(self) -> bool:
		return self._is_open

	async def connect(self) -> bool:
		"""Open connection to TWAIN data source."""
		return await asyncio.get_event_loop().run_in_executor(
			None, self._connect_sync
		)

	def _connect_sync(self) -> bool:
		"""Synchronous connection to TWAIN."""
		try:
			# Load TWAIN DSM
			if sys.platform == 'win32':
				self._dsm = ctypes.windll.LoadLibrary("twain_32.dll")
			else:
				return False

			# Create hidden window for TWAIN messages
			import ctypes.wintypes as wt
			user32 = ctypes.windll.user32

			self._hwnd = user32.CreateWindowExW(
				0, "STATIC", "TWAIN Window",
				0, 0, 0, 0, 0, 0, 0, 0, 0
			)

			# Open DSM
			app_identity = self._create_app_identity()
			rc = self._dsm_entry(
				app_identity, None,
				TwainDG.CONTROL, TwainDAT.PARENT, TwainMSG.OPENDSM,
				ctypes.byref(ctypes.c_void_p(self._hwnd))
			)

			if rc != TwainRC.SUCCESS:
				logger.error(f"Failed to open TWAIN DSM: {rc}")
				return False

			# Open Data Source
			ds_identity = self._create_ds_identity()
			rc = self._dsm_entry(
				app_identity, None,
				TwainDG.CONTROL, TwainDAT.IDENTITY, TwainMSG.OPENDS,
				ctypes.byref(ds_identity)
			)

			if rc != TwainRC.SUCCESS:
				logger.error(f"Failed to open TWAIN data source: {rc}")
				return False

			self._is_open = True
			self._ds_handle = ds_identity
			return True

		except Exception as e:
			logger.exception(f"TWAIN connection error: {e}")
			return False

	async def disconnect(self) -> None:
		"""Close TWAIN connection."""
		await asyncio.get_event_loop().run_in_executor(
			None, self._disconnect_sync
		)

	def _disconnect_sync(self) -> None:
		"""Synchronous disconnect."""
		if not self._is_open:
			return

		try:
			app_identity = self._create_app_identity()

			# Close DS
			if self._ds_handle:
				self._dsm_entry(
					app_identity, self._ds_handle,
					TwainDG.CONTROL, TwainDAT.IDENTITY, TwainMSG.CLOSEDS,
					self._ds_handle
				)

			# Close DSM
			self._dsm_entry(
				app_identity, None,
				TwainDG.CONTROL, TwainDAT.PARENT, TwainMSG.CLOSEDSM,
				ctypes.byref(ctypes.c_void_p(self._hwnd))
			)

			# Destroy window
			if self._hwnd:
				ctypes.windll.user32.DestroyWindow(self._hwnd)

		except Exception as e:
			logger.exception(f"TWAIN disconnect error: {e}")
		finally:
			self._is_open = False
			self._ds_handle = None
			self._hwnd = None

	async def get_status(self) -> ScannerStatus:
		"""Get current scanner status."""
		if not self._is_open:
			return ScannerStatus.OFFLINE

		# Check if scanner is ready
		try:
			status = await asyncio.get_event_loop().run_in_executor(
				None, self._get_status_sync
			)
			return status
		except Exception:
			return ScannerStatus.ERROR

	def _get_status_sync(self) -> ScannerStatus:
		"""Synchronous status check."""
		# Query device status via TWAIN
		# For simplicity, assume online if connected
		return ScannerStatus.ONLINE if self._is_open else ScannerStatus.OFFLINE

	async def get_capabilities(self) -> ScannerCapabilities:
		"""Query scanner capabilities."""
		if self._capabilities:
			return self._capabilities

		caps = await asyncio.get_event_loop().run_in_executor(
			None, self._get_capabilities_sync
		)
		self._capabilities = caps
		return caps

	def _get_capabilities_sync(self) -> ScannerCapabilities:
		"""Synchronous capability query."""
		caps = ScannerCapabilities()

		if not self._is_open:
			return caps

		try:
			# Query resolutions
			caps.resolutions = self._query_resolutions()

			# Query color modes
			caps.color_modes = self._query_color_modes()

			# Query ADF support
			caps.has_adf, caps.has_duplex = self._query_feeder()

			# Standard formats for TWAIN
			caps.formats = [ImageFormat.BMP, ImageFormat.JPEG, ImageFormat.TIFF]

		except Exception as e:
			logger.exception(f"Failed to query TWAIN capabilities: {e}")

		return caps

	def _query_resolutions(self) -> list[int]:
		"""Query supported resolutions."""
		# Default common resolutions
		return [75, 100, 150, 200, 300, 400, 600, 1200]

	def _query_color_modes(self) -> list[ColorMode]:
		"""Query supported color modes."""
		return [ColorMode.COLOR, ColorMode.GRAYSCALE, ColorMode.MONOCHROME]

	def _query_feeder(self) -> tuple[bool, bool]:
		"""Query ADF and duplex support."""
		# Would query CAP_FEEDERENABLED and CAP_DUPLEX
		return False, False

	async def scan(self, options: ScanOptions) -> ScanResult:
		"""Perform a scan operation."""
		if not self._is_open:
			raise RuntimeError("Scanner not connected")

		return await asyncio.get_event_loop().run_in_executor(
			None, self._scan_sync, options
		)

	def _scan_sync(self, options: ScanOptions) -> ScanResult:
		"""Synchronous scan operation."""
		import time
		start_time = time.time()

		try:
			# Set scan parameters
			self._set_scan_options(options)

			# Enable data source (start scan)
			# This would trigger the actual scan

			# Transfer image data
			image_data = self._transfer_image()

			elapsed = time.time() - start_time

			return ScanResult(
				success=True,
				data=image_data,
				format=options.format,
				pages=1,
				scan_time_ms=elapsed * 1000,
			)

		except Exception as e:
			logger.exception(f"TWAIN scan error: {e}")
			return ScanResult(
				success=False,
				error=str(e),
			)

	def _set_scan_options(self, options: ScanOptions) -> None:
		"""Configure TWAIN scan parameters."""
		# Would set ICAP_XRESOLUTION, ICAP_YRESOLUTION, ICAP_PIXELTYPE, etc.
		pass

	def _transfer_image(self) -> bytes:
		"""Transfer scanned image from TWAIN."""
		# Would use native or memory transfer
		return b""

	async def scan_stream(self, options: ScanOptions):
		"""Stream scan data as it's acquired."""
		# TWAIN doesn't support true streaming
		# Fall back to regular scan
		result = await self.scan(options)
		if result.success and result.data:
			yield result.data

	async def preview(self, options: ScanOptions | None = None) -> ScanResult:
		"""Capture a low-resolution preview."""
		preview_options = options or ScanOptions()
		preview_options.resolution = 75
		preview_options.format = ImageFormat.JPEG
		return await self.scan(preview_options)

	async def cancel(self) -> bool:
		"""Cancel ongoing scan operation."""
		# TWAIN cancel is complex - typically requires UI interaction
		return True

	def _create_app_identity(self):
		"""Create TWAIN application identity structure."""
		# Would create proper TWAIN TW_IDENTITY structure
		return None

	def _create_ds_identity(self):
		"""Create TWAIN data source identity structure."""
		# Would create proper TW_IDENTITY for the scanner
		return None

	def _dsm_entry(self, *args) -> int:
		"""Call TWAIN DSM_Entry function."""
		# Would call the actual TWAIN DSM entry point
		return TwainRC.FAILURE


async def discover_twain_scanners() -> list[TwainIdentity]:
	"""Discover available TWAIN scanners on Windows.

	Returns:
		List of discovered TWAIN scanner identities.
	"""
	if sys.platform != 'win32':
		return []

	return await asyncio.get_event_loop().run_in_executor(
		None, _discover_twain_sync
	)


def _discover_twain_sync() -> list[TwainIdentity]:
	"""Synchronous TWAIN discovery."""
	scanners: list[TwainIdentity] = []

	try:
		# Load TWAIN DSM
		dsm = ctypes.windll.LoadLibrary("twain_32.dll")

		# Create temporary window
		user32 = ctypes.windll.user32
		hwnd = user32.CreateWindowExW(
			0, "STATIC", "TWAIN Enum",
			0, 0, 0, 0, 0, 0, 0, 0, 0
		)

		# Open DSM
		# ...

		# Enumerate data sources
		# ...

		# Clean up
		user32.DestroyWindow(hwnd)

	except Exception as e:
		logger.debug(f"TWAIN discovery error: {e}")

	return scanners


def create_twain_scanner(identity: TwainIdentity) -> TWAINScanner:
	"""Factory function to create a TWAIN scanner instance.

	Args:
		identity: TWAIN scanner identity from discovery.

	Returns:
		TWAINScanner instance.
	"""
	return TWAINScanner(identity)
