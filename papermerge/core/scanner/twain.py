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

	def _connect_sync(self) -> bool:
		"""Synchronous connection to TWAIN."""
		try:
			# Load TWAIN DSM
			if sys.platform == 'win32':
				try:
					self._dsm = ctypes.windll.LoadLibrary("twain_32.dll")
				except OSError:
					logger.error("twain_32.dll not found. TWAIN is not available.")
					return False
			else:
				return False

			# Create hidden window for TWAIN messages
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
					ctypes.byref(self._ds_handle)
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

		return await asyncio.get_event_loop().run_in_executor(
			None, self._get_status_sync
		)

	def _get_status_sync(self) -> ScannerStatus:
		"""Synchronous status check."""
		if not self._is_open:
			return ScannerStatus.OFFLINE
		
		# Query device status
		app_identity = self._create_app_identity()
		status = TwainStatus()
		rc = self._dsm_entry(
			app_identity, self._ds_handle,
			TwainDG.CONTROL, TwainDAT.STATUS, TwainMSG.GET,
			ctypes.byref(status)
		)
		
		if rc == TwainRC.SUCCESS:
			return ScannerStatus.ONLINE
		return ScannerStatus.ERROR

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
			caps.resolutions = self._query_capability(TwainCAP.ICAPXRESOLUTION)
			
			# Query color modes
			pixel_types = self._query_capability(TwainCAP.ICAPPIXELTYPE)
			caps.color_modes = self._map_pixel_types(pixel_types)

			# Query ADF support
			feeder_enabled = self._query_capability(TwainCAP.CAP_FEEDERENABLED)
			caps.has_adf = bool(feeder_enabled)
			
			duplex_enabled = self._query_capability(TwainCAP.CAP_DUPLEXENABLED)
			caps.has_duplex = bool(duplex_enabled)

			# Standard formats for TWAIN
			caps.formats = [ImageFormat.BMP, ImageFormat.JPEG, ImageFormat.TIFF]

		except Exception as e:
			logger.exception(f"Failed to query TWAIN capabilities: {e}")

		return caps

	def _query_capability(self, cap_id: int) -> Any:
		"""Query a specific TWAIN capability."""
		# This is a simplified version of capability negotiation
		# In a real implementation, this would handle TW_CAPABILITY, TW_ONEVALUE, etc.
		return []

	def _map_pixel_types(self, pixel_types: list[int]) -> list[ColorMode]:
		"""Map TWAIN pixel types to ColorMode."""
		mapping = {
			0: ColorMode.MONOCHROME,
			1: ColorMode.GRAYSCALE,
			2: ColorMode.COLOR,
		}
		return [mapping[pt] for pt in pixel_types if pt in mapping]

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
			ui = TwainUserInterface(ShowUI=False, ModalUI=False, hParent=self._hwnd)
			app_identity = self._create_app_identity()
			
			rc = self._dsm_entry(
				app_identity, self._ds_handle,
				TwainDG.CONTROL, TwainDAT.USERINTERFACE, TwainMSG.ENABLEDS,
				ctypes.byref(ui)
			)

			if rc != TwainRC.SUCCESS:
				return ScanResult(success=False, error=f"Failed to enable DS: {rc}")

			# Transfer image data
			# This would normally involve a message loop to wait for XFERDONE
			image_data = self._transfer_image()

			elapsed = time.time() - start_time

			return ScanResult(
				success=True,
				pages=[image_data] if image_data else [],
				page_count=1 if image_data else 0,
				format=options.format,
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
		# Set resolution
		self._set_capability(TwainCAP.ICAPXRESOLUTION, options.resolution)
		self._set_capability(TwainCAP.ICAPYRESOLUTION, options.resolution)
		
		# Set pixel type
		pixel_type = {
			ColorMode.COLOR: 2,
			ColorMode.GRAYSCALE: 1,
			ColorMode.MONOCHROME: 0,
		}.get(options.color_mode, 2)
		self._set_capability(TwainCAP.ICAPPIXELTYPE, pixel_type)

	def _set_capability(self, cap_id: int, value: Any) -> bool:
		"""Set a TWAIN capability value."""
		return True

	def _transfer_image(self) -> bytes:
		"""Transfer scanned image from TWAIN."""
		# Simplified: would use TwainDG.IMAGE, TwainDAT.IMAGENATIVEXFER, TwainMSG.GET
		return b""

	async def scan_stream(self, options: ScanOptions):
		"""Stream scan data as it's acquired."""
		result = await self.scan(options)
		if result.success:
			for i, page in enumerate(result.pages):
				yield (i, page)

	async def preview(self, options: ScanOptions | None = None) -> ScanResult:
		"""Capture a low-resolution preview."""
		preview_options = options or ScanOptions()
		preview_options.resolution = 75
		preview_options.format = ImageFormat.JPEG
		return await self.scan(preview_options)

	async def cancel(self) -> bool:
		"""Cancel ongoing scan operation."""
		if not self._is_open:
			return True
		
		app_identity = self._create_app_identity()
		rc = self._dsm_entry(
			app_identity, self._ds_handle,
			TwainDG.CONTROL, TwainDAT.USERINTERFACE, TwainMSG.DISABLEDS,
			ctypes.byref(TwainUserInterface(hParent=self._hwnd))
		)
		return rc == TwainRC.SUCCESS

	def _create_app_identity(self):
		"""Create TWAIN application identity structure."""
		identity = TwainIdentityStruct()
		identity.Id = 0
		identity.Version.MajorNum = 1
		identity.Version.MinorNum = 0
		identity.Version.Language = 13 # English
		identity.Version.Country = 1 # USA
		identity.Version.Info = b"ArchivaPro Ingestion"
		identity.ProtocolMajor = 2
		identity.ProtocolMinor = 4
		identity.SupportedGroups = TwainDG.CONTROL | TwainDG.IMAGE
		identity.Manufacturer = b"Datacraft"
		identity.ProductFamily = b"ArchivaPro"
		identity.ProductName = b"ArchivaPro Scanner Bridge"
		return identity

	def _create_ds_identity(self):
		"""Create TWAIN data source identity structure."""
		identity = TwainIdentityStruct()
		identity.ProductName = self._identity.product_name.encode('utf-8')
		return identity

	def _dsm_entry(self, pOrigin, pDest, dg, dat, msg, pData) -> int:
		"""Call TWAIN DSM_Entry function."""
		if not self._dsm:
			return TwainRC.FAILURE
		
		# DSM_Entry(pOrigin, pDest, DG, DAT, MSG, pData)
		func = self._dsm.DSM_Entry
		func.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, 
						 ctypes.c_uint16, ctypes.c_uint16, ctypes.c_void_p]
		func.restype = ctypes.c_uint16
		
		return func(ctypes.byref(pOrigin) if pOrigin else None,
					ctypes.byref(pDest) if pDest else None,
					dg, dat, msg, pData)


# TWAIN Structures for ctypes
class TwainVersion(ctypes.Structure):
	_fields_ = [
		("MajorNum", ctypes.c_uint16),
		("MinorNum", ctypes.c_uint16),
		("Language", ctypes.c_uint16),
		("Country", ctypes.c_uint16),
		("Info", ctypes.c_char * 34),
	]

class TwainIdentityStruct(ctypes.Structure):
	_fields_ = [
		("Id", ctypes.c_uint32),
		("Version", TwainVersion),
		("ProtocolMajor", ctypes.c_uint16),
		("ProtocolMinor", ctypes.c_uint16),
		("SupportedGroups", ctypes.c_uint32),
		("Manufacturer", ctypes.c_char * 34),
		("ProductFamily", ctypes.c_char * 34),
		("ProductName", ctypes.c_char * 34),
	]

class TwainStatus(ctypes.Structure):
	_fields_ = [
		("ConditionCode", ctypes.c_uint16),
		("Reserved", ctypes.c_uint16),
	]

class TwainUserInterface(ctypes.Structure):
	_fields_ = [
		("ShowUI", ctypes.c_uint16),
		("ModalUI", ctypes.c_uint16),
		("hParent", ctypes.c_void_p),
	]


async def discover_twain_scanners() -> list[TwainIdentity]:
	"""Discover available TWAIN scanners on Windows."""
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
		app = TwainIdentityStruct()
		app.ProductName = b"ArchivaPro Discovery"
		
		func = dsm.DSM_Entry
		rc = func(ctypes.byref(app), None, TwainDG.CONTROL, TwainDAT.PARENT, 
				  TwainMSG.OPENDSM, ctypes.byref(ctypes.c_void_p(hwnd)))

		if rc == TwainRC.SUCCESS:
			# Get first DS
			ds = TwainIdentityStruct()
			rc = func(ctypes.byref(app), None, TwainDG.CONTROL, TwainDAT.IDENTITY, 
					  TwainMSG.GETFIRST, ctypes.byref(ds))
			
			while rc == TwainRC.SUCCESS:
				scanners.append(TwainIdentity(
					id=ds.Id,
					product_name=ds.ProductName.decode('utf-8', 'ignore').strip('\x00'),
					manufacturer=ds.Manufacturer.decode('utf-8', 'ignore').strip('\x00'),
					product_family=ds.ProductFamily.decode('utf-8', 'ignore').strip('\x00'),
				))
				
				# Get next DS
				rc = func(ctypes.byref(app), None, TwainDG.CONTROL, TwainDAT.IDENTITY, 
						  TwainMSG.GETNEXT, ctypes.byref(ds))

			# Close DSM
			func(ctypes.byref(app), None, TwainDG.CONTROL, TwainDAT.PARENT, 
				 TwainMSG.CLOSEDSM, ctypes.byref(ctypes.c_void_p(hwnd)))

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
