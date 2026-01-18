# (c) Copyright Datacraft, 2026
"""SANE scanner wrapper for Linux/macOS."""
import asyncio
import io
import logging
import time
from typing import Any, AsyncIterator

from .base import Scanner, ScannerProtocol, ScanOptions, ScanResult
from .capabilities import ScannerCapabilities, ColorMode

logger = logging.getLogger(__name__)


class SANEScanner(Scanner):
	"""
	SANE (Scanner Access Now Easy) scanner wrapper.

	Requires python-sane package and SANE libraries.
	Works on Linux and macOS.
	"""

	protocol = ScannerProtocol.SANE

	def __init__(self, device_name: str):
		"""
		Initialize SANE scanner.

		Args:
			device_name: SANE device identifier (e.g., 'epson2:libusb:001:004')
		"""
		self._device_name = device_name
		self._device = None
		self._initialized = False
		self._capabilities: ScannerCapabilities | None = None
		self._info: dict = {}
		self._lock = asyncio.Lock()

	@property
	def id(self) -> str:
		return f"sane://{self._device_name}"

	@property
	def name(self) -> str:
		return self._info.get('name', self._device_name)

	@property
	def manufacturer(self) -> str:
		return self._info.get('vendor', 'Unknown')

	@property
	def model(self) -> str:
		return self._info.get('model', 'Unknown')

	async def _ensure_initialized(self):
		"""Ensure SANE is initialized and device is open."""
		if self._initialized:
			return

		async with self._lock:
			if self._initialized:
				return

			try:
				import sane

				# Initialize SANE
				sane.init()

				# Find our device
				devices = sane.get_devices()
				for dev in devices:
					if dev[0] == self._device_name:
						self._info = {
							'name': dev[0],
							'vendor': dev[1],
							'model': dev[2],
							'type': dev[3],
						}
						break

				# Open device
				self._device = sane.open(self._device_name)
				self._initialized = True

				logger.info(f"SANE device opened: {self._device_name}")

			except ImportError:
				raise RuntimeError("python-sane not installed")
			except Exception as e:
				raise RuntimeError(f"Failed to open SANE device: {e}")

	async def close(self):
		"""Close SANE device."""
		if self._device:
			try:
				self._device.close()
			except Exception:
				pass
			self._device = None
			self._initialized = False

	async def __aenter__(self):
		await self._ensure_initialized()
		return self

	async def __aexit__(self, *args):
		await self.close()

	async def is_available(self) -> bool:
		"""Check if scanner is available."""
		try:
			await self._ensure_initialized()
			return self._device is not None
		except Exception:
			return False

	async def get_capabilities(self) -> ScannerCapabilities:
		"""Get scanner capabilities from SANE options."""
		if self._capabilities:
			return self._capabilities

		await self._ensure_initialized()

		# Get all device options
		options = []
		for opt_name in dir(self._device):
			if opt_name.startswith('_'):
				continue
			try:
				opt = getattr(self._device, opt_name)
				if hasattr(opt, 'constraint'):
					options.append({
						'name': opt_name,
						'value': getattr(self._device, opt_name, None),
						'constraint': opt.constraint if hasattr(opt, 'constraint') else None,
					})
			except Exception:
				pass

		self._capabilities = ScannerCapabilities.from_sane(options)
		return self._capabilities

	async def scan(self, options: ScanOptions) -> ScanResult:
		"""Perform a scan operation."""
		start_time = time.time()
		pages = []
		errors = []

		try:
			await self._ensure_initialized()

			# Configure scan options
			await self._configure_options(options)

			# Perform scan (run in thread pool to avoid blocking)
			def do_scan():
				self._device.start()
				pil_image = self._device.snap()
				return pil_image

			pil_image = await asyncio.to_thread(do_scan)

			# Convert to bytes
			output = io.BytesIO()
			format_map = {
				'jpeg': 'JPEG',
				'png': 'PNG',
				'tiff': 'TIFF',
			}
			pil_format = format_map.get(options.format, 'JPEG')
			save_kwargs = {}
			if options.format == 'jpeg':
				save_kwargs['quality'] = options.quality

			pil_image.save(output, format=pil_format, **save_kwargs)
			pages.append(output.getvalue())

			# Handle ADF multi-page scanning
			if options.batch_mode and options.input_source in ('adf', 'adf_duplex'):
				while True:
					try:
						pil_image = await asyncio.to_thread(
							lambda: (self._device.start(), self._device.snap())[1]
						)
						output = io.BytesIO()
						pil_image.save(output, format=pil_format, **save_kwargs)
						pages.append(output.getvalue())

						if options.max_pages and len(pages) >= options.max_pages:
							break
					except Exception as e:
						# ADF empty or other error
						if 'no more' in str(e).lower() or 'empty' in str(e).lower():
							break
						logger.warning(f"ADF scan stopped: {e}")
						break

			return ScanResult(
				success=True,
				pages=pages,
				page_count=len(pages),
				format=options.format,
				scan_time_ms=(time.time() - start_time) * 1000,
			)

		except Exception as e:
			logger.error(f"SANE scan error: {e}")
			errors.append(str(e))

		return ScanResult(
			success=False,
			pages=pages,
			page_count=len(pages),
			format=options.format,
			scan_time_ms=(time.time() - start_time) * 1000,
			errors=errors,
		)

	async def scan_stream(
		self,
		options: ScanOptions
	) -> AsyncIterator[tuple[int, bytes]]:
		"""Stream scanned pages as they complete."""
		await self._ensure_initialized()
		await self._configure_options(options)

		page_num = 0
		format_map = {
			'jpeg': 'JPEG',
			'png': 'PNG',
			'tiff': 'TIFF',
		}
		pil_format = format_map.get(options.format, 'JPEG')
		save_kwargs = {'quality': options.quality} if options.format == 'jpeg' else {}

		while True:
			try:
				def do_scan():
					self._device.start()
					return self._device.snap()

				pil_image = await asyncio.to_thread(do_scan)

				output = io.BytesIO()
				pil_image.save(output, format=pil_format, **save_kwargs)

				yield (page_num, output.getvalue())
				page_num += 1

				if options.max_pages and page_num >= options.max_pages:
					break

				# For single-page sources (platen), stop after first page
				if options.input_source == 'platen':
					break

			except Exception as e:
				if 'no more' in str(e).lower():
					break
				raise

	async def _configure_options(self, options: ScanOptions):
		"""Configure SANE device options."""
		# Resolution
		if hasattr(self._device, 'resolution'):
			try:
				self._device.resolution = options.resolution
			except Exception as e:
				logger.debug(f"Could not set resolution: {e}")

		# Color mode
		if hasattr(self._device, 'mode'):
			mode_map = {
				'color': 'Color',
				'grayscale': 'Gray',
				'monochrome': 'Lineart',
			}
			try:
				self._device.mode = mode_map.get(options.color_mode, 'Color')
			except Exception as e:
				logger.debug(f"Could not set mode: {e}")

		# Input source
		if hasattr(self._device, 'source'):
			source_map = {
				'platen': 'Flatbed',
				'adf': 'ADF',
				'adf_duplex': 'ADF Duplex',
			}
			try:
				self._device.source = source_map.get(options.input_source, 'Flatbed')
			except Exception as e:
				logger.debug(f"Could not set source: {e}")

		# Scan area
		if options.x_offset is not None and hasattr(self._device, 'tl_x'):
			try:
				self._device.tl_x = options.x_offset
			except Exception:
				pass
		if options.y_offset is not None and hasattr(self._device, 'tl_y'):
			try:
				self._device.tl_y = options.y_offset
			except Exception:
				pass
		if options.width is not None and hasattr(self._device, 'br_x'):
			try:
				self._device.br_x = (options.x_offset or 0) + options.width
			except Exception:
				pass
		if options.height is not None and hasattr(self._device, 'br_y'):
			try:
				self._device.br_y = (options.y_offset or 0) + options.height
			except Exception:
				pass

		# Brightness/Contrast
		if options.brightness != 0 and hasattr(self._device, 'brightness'):
			try:
				self._device.brightness = options.brightness
			except Exception:
				pass
		if options.contrast != 0 and hasattr(self._device, 'contrast'):
			try:
				self._device.contrast = options.contrast
			except Exception:
				pass

	async def cancel_scan(self) -> bool:
		"""Cancel current scan operation."""
		if self._device:
			try:
				self._device.cancel()
				return True
			except Exception as e:
				logger.error(f"Error cancelling scan: {e}")
		return False

	async def get_status(self) -> dict[str, Any]:
		"""Get scanner status."""
		try:
			await self._ensure_initialized()
			return {
				'available': self._device is not None,
				'protocol': self.protocol.value,
				'device_name': self._device_name,
				'vendor': self._info.get('vendor'),
				'model': self._info.get('model'),
			}
		except Exception as e:
			return {
				'available': False,
				'error': str(e),
			}
