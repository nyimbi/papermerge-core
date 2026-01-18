# (c) Copyright Datacraft, 2026
"""eSCL (AirScan) scanner client implementation."""
import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import AsyncIterator, Any

import httpx

from .base import Scanner, ScannerProtocol, ScanOptions, ScanResult, ScanJobStatus
from .capabilities import (
	ScannerCapabilities, ColorMode, InputSource, ImageFormat,
	Resolution, ADFCapabilities, ScanArea
)

logger = logging.getLogger(__name__)


# eSCL XML namespaces
NAMESPACES = {
	'scan': 'http://schemas.hp.com/imaging/escl/2011/05/03',
	'pwg': 'http://www.pwg.org/schemas/2010/12/sm',
}


class ESCLScanner(Scanner):
	"""
	eSCL (Apple AirScan) scanner client.

	Implements the eSCL protocol over HTTP/HTTPS for
	network-connected scanners.
	"""

	protocol = ScannerProtocol.ESCL

	def __init__(
		self,
		host: str,
		port: int = 80,
		root_path: str = '/eSCL',
		use_https: bool = False,
		timeout: float = 30.0,
		verify_ssl: bool = True,
	):
		self._host = host
		self._port = port
		self._root_path = root_path.rstrip('/')
		self._scheme = 'https' if use_https else 'http'
		self._timeout = timeout
		self._verify_ssl = verify_ssl

		self._base_url = f"{self._scheme}://{host}:{port}{self._root_path}"
		self._client = httpx.AsyncClient(
			timeout=timeout,
			verify=verify_ssl,
			follow_redirects=True,
		)

		self._capabilities: ScannerCapabilities | None = None
		self._info: dict = {}
		self._current_job_url: str | None = None

	@property
	def id(self) -> str:
		return f"escl://{self._host}:{self._port}"

	@property
	def name(self) -> str:
		return self._info.get('MakeAndModel', f'eSCL Scanner at {self._host}')

	@property
	def manufacturer(self) -> str:
		return self._info.get('Manufacturer', 'Unknown')

	@property
	def model(self) -> str:
		return self._info.get('Model', 'Unknown')

	async def close(self):
		"""Close HTTP client."""
		await self._client.aclose()

	async def __aenter__(self):
		return self

	async def __aexit__(self, *args):
		await self.close()

	async def is_available(self) -> bool:
		"""Check if scanner is available."""
		try:
			response = await self._client.get(
				f"{self._base_url}/ScannerStatus",
				timeout=5.0,
			)
			if response.status_code == 200:
				# Parse status
				root = ET.fromstring(response.text)
				state = root.find('.//pwg:State', NAMESPACES)
				if state is not None:
					return state.text == 'Idle'
			return False
		except Exception as e:
			logger.debug(f"Scanner not available: {e}")
			return False

	async def get_status(self) -> dict[str, Any]:
		"""Get detailed scanner status."""
		try:
			response = await self._client.get(f"{self._base_url}/ScannerStatus")
			response.raise_for_status()

			root = ET.fromstring(response.text)
			status = {
				'available': True,
				'protocol': self.protocol.value,
			}

			state = root.find('.//pwg:State', NAMESPACES)
			if state is not None:
				status['state'] = state.text

			jobs = root.find('.//scan:Jobs', NAMESPACES)
			if jobs is not None:
				status['active_jobs'] = len(list(jobs))

			adf_state = root.find('.//scan:AdfState', NAMESPACES)
			if adf_state is not None:
				status['adf_state'] = adf_state.text

			return status

		except Exception as e:
			return {
				'available': False,
				'error': str(e),
			}

	async def get_capabilities(self) -> ScannerCapabilities:
		"""Fetch and parse scanner capabilities."""
		if self._capabilities:
			return self._capabilities

		response = await self._client.get(f"{self._base_url}/ScannerCapabilities")
		response.raise_for_status()

		self._capabilities = self._parse_capabilities(response.text)
		return self._capabilities

	def _parse_capabilities(self, xml_text: str) -> ScannerCapabilities:
		"""Parse eSCL capabilities XML."""
		root = ET.fromstring(xml_text)
		data = {}

		# Extract scanner info
		make_model = root.find('.//pwg:MakeAndModel', NAMESPACES)
		if make_model is not None:
			self._info['MakeAndModel'] = make_model.text

		serial = root.find('.//pwg:SerialNumber', NAMESPACES)
		if serial is not None:
			self._info['SerialNumber'] = serial.text

		# Parse input sources
		sources = []
		if root.find('.//scan:Platen', NAMESPACES) is not None:
			sources.append('Platen')
		if root.find('.//scan:Adf', NAMESPACES) is not None:
			sources.append('Feeder')
			# Check for duplex
			duplex = root.find('.//scan:AdfDuplex', NAMESPACES)
			if duplex is not None:
				sources.append('ADFDuplex')
		data['InputSources'] = sources

		# Parse resolutions
		resolutions = []
		for res in root.findall('.//scan:DiscreteResolution', NAMESPACES):
			x_res = res.find('scan:XResolution', NAMESPACES)
			if x_res is not None:
				try:
					resolutions.append(int(x_res.text))
				except (ValueError, TypeError):
					pass
		data['Resolutions'] = sorted(set(resolutions)) if resolutions else [150, 300, 600]

		# Parse color modes
		color_modes = []
		for mode in root.findall('.//scan:ColorMode', NAMESPACES):
			if mode.text:
				color_modes.append(mode.text)
		data['ColorModes'] = color_modes

		# Parse document formats
		formats = []
		for fmt in root.findall('.//pwg:DocumentFormat', NAMESPACES):
			if fmt.text:
				formats.append(fmt.text)
		# Also check DocumentFormatExt
		for fmt in root.findall('.//scan:DocumentFormatExt', NAMESPACES):
			if fmt.text:
				formats.append(fmt.text)
		data['DocumentFormats'] = formats

		# Parse platen dimensions
		platen = root.find('.//scan:Platen/scan:PlatenInputCaps', NAMESPACES)
		if platen is not None:
			platen_caps = {}
			min_w = platen.find('.//scan:MinWidth', NAMESPACES)
			max_w = platen.find('.//scan:MaxWidth', NAMESPACES)
			min_h = platen.find('.//scan:MinHeight', NAMESPACES)
			max_h = platen.find('.//scan:MaxHeight', NAMESPACES)

			if min_w is not None:
				platen_caps['MinWidth'] = int(min_w.text)
			if max_w is not None:
				platen_caps['MaxWidth'] = int(max_w.text)
			if min_h is not None:
				platen_caps['MinHeight'] = int(min_h.text)
			if max_h is not None:
				platen_caps['MaxHeight'] = int(max_h.text)

			data['PlatenInputCaps'] = platen_caps

		return ScannerCapabilities.from_escl(data)

	async def scan(self, options: ScanOptions) -> ScanResult:
		"""Perform a scan operation."""
		start_time = time.time()
		pages = []
		errors = []

		try:
			# Create scan job
			job_url = await self._create_scan_job(options)
			self._current_job_url = job_url

			# Wait for job to complete and retrieve pages
			page_num = 0
			while True:
				page_data = await self._get_next_page(job_url, page_num)
				if page_data is None:
					break
				pages.append(page_data)
				page_num += 1

				if options.max_pages and page_num >= options.max_pages:
					break

			return ScanResult(
				success=True,
				pages=pages,
				page_count=len(pages),
				format=options.format,
				scan_time_ms=(time.time() - start_time) * 1000,
			)

		except httpx.HTTPStatusError as e:
			errors.append(f"HTTP error: {e.response.status_code}")
		except Exception as e:
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
		job_url = await self._create_scan_job(options)
		self._current_job_url = job_url

		page_num = 0
		while True:
			page_data = await self._get_next_page(job_url, page_num)
			if page_data is None:
				break

			yield (page_num, page_data)
			page_num += 1

			if options.max_pages and page_num >= options.max_pages:
				break

	async def _create_scan_job(self, options: ScanOptions) -> str:
		"""Create a scan job and return the job URL."""
		# Build scan settings XML
		scan_settings = self._build_scan_settings(options)

		response = await self._client.post(
			f"{self._base_url}/ScanJobs",
			content=scan_settings,
			headers={'Content-Type': 'application/xml'},
		)

		if response.status_code == 201:
			# Job created, get location
			job_url = response.headers.get('Location')
			if job_url:
				if not job_url.startswith('http'):
					job_url = f"{self._base_url}/ScanJobs{job_url}"
				return job_url

		response.raise_for_status()
		raise RuntimeError("Failed to create scan job")

	def _build_scan_settings(self, options: ScanOptions) -> str:
		"""Build eSCL scan settings XML."""
		# Map color mode
		color_map = {
			'color': 'RGB24',
			'grayscale': 'Grayscale8',
			'monochrome': 'BlackAndWhite1',
		}
		color_mode = color_map.get(options.color_mode, 'RGB24')

		# Map input source
		source_map = {
			'platen': 'Platen',
			'adf': 'Feeder',
			'adf_duplex': 'Feeder',
		}
		input_source = source_map.get(options.input_source, 'Platen')

		# Map format
		format_map = {
			'jpeg': 'image/jpeg',
			'png': 'image/png',
			'tiff': 'image/tiff',
			'pdf': 'application/pdf',
		}
		doc_format = format_map.get(options.format, 'image/jpeg')

		xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
                   xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
    <pwg:Version>2.6</pwg:Version>
    <pwg:ScanRegions>
        <pwg:ScanRegion>
            <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>
            <pwg:XOffset>{int((options.x_offset or 0) / 25.4 * 300)}</pwg:XOffset>
            <pwg:YOffset>{int((options.y_offset or 0) / 25.4 * 300)}</pwg:YOffset>
            <pwg:Width>{int((options.width or 215.9) / 25.4 * 300)}</pwg:Width>
            <pwg:Height>{int((options.height or 297) / 25.4 * 300)}</pwg:Height>
        </pwg:ScanRegion>
    </pwg:ScanRegions>
    <scan:InputSource>{input_source}</scan:InputSource>
    <scan:ColorMode>{color_mode}</scan:ColorMode>
    <scan:XResolution>{options.resolution}</scan:XResolution>
    <scan:YResolution>{options.resolution}</scan:YResolution>
    <pwg:DocumentFormat>{doc_format}</pwg:DocumentFormat>'''

		if options.duplex and options.input_source in ('adf', 'adf_duplex'):
			xml += '\n    <scan:Duplex>true</scan:Duplex>'

		if options.brightness != 0:
			# eSCL brightness is 1-100, with 50 as neutral
			brightness = 50 + (options.brightness // 2)
			xml += f'\n    <scan:Brightness>{brightness}</scan:Brightness>'

		if options.contrast != 0:
			contrast = 50 + (options.contrast // 2)
			xml += f'\n    <scan:Contrast>{contrast}</scan:Contrast>'

		xml += '\n</scan:ScanSettings>'
		return xml

	async def _get_next_page(self, job_url: str, page_num: int) -> bytes | None:
		"""Retrieve the next scanned page."""
		# Poll for job completion
		max_wait = 120  # seconds
		poll_interval = 0.5
		elapsed = 0

		while elapsed < max_wait:
			status = await self._get_job_status(job_url)

			if status == 'Completed':
				# Get page data
				page_url = f"{job_url}/NextDocument"
				response = await self._client.get(page_url)

				if response.status_code == 200:
					return response.content
				elif response.status_code == 404:
					# No more pages
					return None
				else:
					response.raise_for_status()

			elif status == 'Processing':
				await asyncio.sleep(poll_interval)
				elapsed += poll_interval

			elif status in ('Canceled', 'Aborted'):
				return None

			else:
				logger.warning(f"Unknown job status: {status}")
				await asyncio.sleep(poll_interval)
				elapsed += poll_interval

		raise TimeoutError("Scan job timed out")

	async def _get_job_status(self, job_url: str) -> str:
		"""Get status of a scan job."""
		try:
			response = await self._client.get(job_url)
			if response.status_code == 200:
				root = ET.fromstring(response.text)
				state = root.find('.//pwg:JobState', NAMESPACES)
				if state is not None:
					return state.text
				# Try alternative element
				state = root.find('.//scan:JobState', NAMESPACES)
				if state is not None:
					return state.text
			return 'Unknown'
		except Exception as e:
			logger.error(f"Error getting job status: {e}")
			return 'Unknown'

	async def cancel_scan(self) -> bool:
		"""Cancel current scan operation."""
		if not self._current_job_url:
			return False

		try:
			response = await self._client.delete(self._current_job_url)
			self._current_job_url = None
			return response.status_code in (200, 204)
		except Exception as e:
			logger.error(f"Error cancelling scan: {e}")
			return False

	async def scan_preview(self) -> bytes | None:
		"""Get a quick preview scan."""
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
