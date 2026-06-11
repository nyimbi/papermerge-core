# (c) Copyright Datacraft, 2026
"""eSCL (AirScan) scanner client implementation."""
import asyncio
import logging
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import AsyncIterator, Any
from urllib.parse import urlparse, urljoin

import httpx

from .base import Scanner, ScannerProtocol, ScanOptions, ScanResult, ScanJobStatus
from .capabilities import (
	ScannerCapabilities, ColorMode, InputSource, ImageFormat,
	Resolution, ADFCapabilities, ScanArea
)
from .quirks import (
	DeviceQuirks, QuirkFlag, detect_quirks,
	get_effective_resolution, should_retry_on_status
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
	network-connected scanners with full device quirks support.
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

		# Create a permissive SSL context for older scanners
		ssl_context = None
		if use_https and not verify_ssl:
			ssl_context = ssl.create_default_context()
			ssl_context.check_hostname = False
			ssl_context.verify_mode = ssl.CERT_NONE
			# Allow older TLS versions for legacy scanner firmware
			ssl_context.minimum_version = ssl.TLSVersion.TLSv1
			ssl_context.set_ciphers('DEFAULT:@SECLEVEL=0')

		self._client = httpx.AsyncClient(
			timeout=timeout,
			verify=ssl_context if ssl_context else verify_ssl,
			follow_redirects=True,
		)

		self._capabilities: ScannerCapabilities | None = None
		self._info: dict = {}
		self._current_job_url: str | None = None
		
		# Device quirks - will be detected when capabilities are fetched
		self._quirks: DeviceQuirks = DeviceQuirks()
		self._quirks_detected: bool = False
		self._server_header: str = ''

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

	async def _detect_and_apply_quirks(self) -> None:
		"""Detect device quirks from capabilities response and server header."""
		if self._quirks_detected:
			return
		
		model = self._info.get('MakeAndModel', '')
		manufacturer = self._info.get('Manufacturer', '')
		
		self._quirks = detect_quirks(model, manufacturer, self._server_header)
		self._quirks_detected = True
		
		if self._quirks.flags:
			logger.info(f"[ESCL] Detected quirks for {model}: {self._quirks}")
		else:
			logger.debug(f"[ESCL] No quirks detected for {model}")

	def _get_request_headers(self) -> dict[str, str]:
		"""Build HTTP headers with quirk adjustments."""
		headers = {'Accept': '*/*'}
		
		# HP localhost header quirk
		if self._quirks.has(QuirkFlag.LOCALHOST_HEADER):
			headers['Host'] = self._quirks.host_header or 'localhost'
			logger.debug(f"[ESCL] Applying LOCALHOST_HEADER quirk: Host={headers['Host']}")
		
		# EPSON port in host quirk
		elif self._quirks.has(QuirkFlag.PORT_IN_HOST):
			headers['Host'] = f"{self._host}:{self._port}"
			logger.debug(f"[ESCL] Applying PORT_IN_HOST quirk: Host={headers['Host']}")
		
		return headers

	async def _cleanup_job(self, job_url: str) -> bool:
		"""
		Clean up scan job by sending DELETE request.
		
		Some devices (Xerox B205/B215) break if cleanup is attempted,
		so we check the SKIP_CLEANUP quirk first.
		"""
		if not job_url:
			return True
		
		if self._quirks.has(QuirkFlag.SKIP_CLEANUP):
			logger.info(f"[ESCL] Skipping cleanup (device quirk): {job_url}")
			return True
		
		logger.info(f"[ESCL] Cleanup: DELETE {job_url}")
		try:
			async with httpx.AsyncClient(
				timeout=10.0,
				headers=self._get_request_headers()
			) as client:
				response = await client.delete(job_url)
				success = response.status_code in (200, 204, 404)
				if success:
					logger.debug(f"[ESCL] Cleanup successful: {response.status_code}")
				else:
					logger.warning(f"[ESCL] Cleanup returned: {response.status_code}")
				return success
		except Exception as e:
			logger.warning(f"[ESCL] Cleanup failed: {e}")
			return False

	async def _check_adf_state(self) -> tuple[bool, str]:
		"""
		Check ADF state before scanning (for devices that require it).
		
		Returns:
			Tuple of (is_ready, state_description)
		"""
		if not self._quirks.has(QuirkFlag.CHECK_ADF_STATE):
			return True, "check_not_required"
		
		try:
			response = await self._client.get(
				f"{self._base_url}/ScannerStatus",
				headers=self._get_request_headers()
			)
			if response.status_code != 200:
				return True, "status_unavailable"
			
			root = ET.fromstring(response.text)
			adf_state = root.find('.//scan:AdfState', NAMESPACES)
			
			if adf_state is not None:
				state = adf_state.text
				# Common ADF states
				if state in ('ScannerAdfLoaded', 'Loaded', 'Ready'):
					return True, state
				elif state in ('ScannerAdfEmpty', 'Empty'):
					return False, "ADF is empty - please load documents"
				elif state in ('ScannerAdfJam', 'Jammed'):
					return False, "ADF paper jam detected"
				elif state in ('ScannerAdfCoverOpen', 'CoverOpen'):
					return False, "ADF cover is open"
				else:
					return True, state  # Unknown state - proceed anyway
			
			return True, "no_adf_state"
		except Exception as e:
			logger.warning(f"[ESCL] ADF state check failed: {e}")
			return True, "check_failed"

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
		
		# Capture server header for quirks detection
		self._server_header = response.headers.get('Server', '')
		logger.debug(f"[ESCL] Server header: {self._server_header}")

		self._capabilities = self._parse_capabilities(response.text)
		
		# Detect and apply device quirks after parsing capabilities
		await self._detect_and_apply_quirks()
		
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
		"""Perform a scan operation with full quirks support."""
		print(f"[ESCL] Starting scan: resolution={options.resolution}, format={options.format}", file=sys.stderr, flush=True)
		logger.info(f"[ESCL] Starting scan with options: resolution={options.resolution}, format={options.format}")
		start_time = time.time()
		pages = []
		errors = []
		job_url = None

		try:
			# Ensure quirks are detected
			if not self._quirks_detected:
				await self.get_capabilities()
			
			# Apply resolution cap if device has one
			effective_resolution = get_effective_resolution(self._quirks, options.resolution)
			if effective_resolution != options.resolution:
				logger.info(f"[ESCL] Resolution capped from {options.resolution} to {effective_resolution} (device quirk)")
				options = ScanOptions(
					**{**options.__dict__, 'resolution': effective_resolution}
				)
			
			# Check ADF state for devices that require it
			if options.input_source in ('adf', 'adf_duplex'):
				adf_ready, adf_state = await self._check_adf_state()
				logger.info(f"[ESCL] ADF state: {adf_state}")
				if not adf_ready:
					errors.append(f"ADF error: {adf_state}")
					return ScanResult(
						success=False,
						pages=[],
						page_count=0,
						format=options.format,
						scan_time_ms=(time.time() - start_time) * 1000,
						errors=errors,
					)
			
			# Apply init delay if device needs it
			if self._quirks.init_delay_ms > 0:
				logger.info(f"[ESCL] Applying init delay: {self._quirks.init_delay_ms}ms")
				await asyncio.sleep(self._quirks.init_delay_ms / 1000)
			
			# Create scan job
			job_url = await self._create_scan_job(options)
			self._current_job_url = job_url
			logger.info(f"[ESCL] Scan job URL: {job_url}")
			print(f"[ESCL] Job URL: {job_url}", file=sys.stderr, flush=True)

			# Wait for job to complete and retrieve pages
			page_num = 0
			while True:
				logger.info(f"[ESCL] Fetching page {page_num}...")
				page_data = await self._get_next_page(job_url, page_num)
				if page_data is None:
					logger.info(f"[ESCL] No more pages (got None for page {page_num})")
					print(f"[ESCL] Scan complete: {page_num} pages", file=sys.stderr, flush=True)
					break
				logger.info(f"[ESCL] Got page {page_num}, size: {len(page_data)} bytes")
				print(f"[ESCL] Got page {page_num}: {len(page_data)} bytes", file=sys.stderr, flush=True)
				pages.append(page_data)
				page_num += 1

				if options.max_pages and page_num >= options.max_pages:
					logger.info(f"[ESCL] Reached max_pages limit: {options.max_pages}")
					break

			scan_time = (time.time() - start_time) * 1000
			logger.info(f"[ESCL] Scan completed successfully: {len(pages)} pages in {scan_time:.0f}ms")
			print(f"[ESCL] SUCCESS: {len(pages)} pages in {scan_time:.0f}ms", file=sys.stderr, flush=True)
			
			return ScanResult(
				success=True,
				pages=pages,
				page_count=len(pages),
				format=options.format,
				scan_time_ms=scan_time,
			)

		except httpx.HTTPStatusError as e:
			logger.error(f"[ESCL] HTTP error during scan: {e.response.status_code}")
			print(f"[ESCL] HTTP error: {e.response.status_code}", file=sys.stderr, flush=True)
			errors.append(f"HTTP error: {e.response.status_code}")
		except TimeoutError as e:
			logger.error(f"[ESCL] Timeout error during scan: {e}")
			print(f"[ESCL] Timeout: {e}", file=sys.stderr, flush=True)
			errors.append(f"Timeout: {str(e)}")
		except Exception as e:
			logger.error(f"[ESCL] Unexpected error during scan: {e}", exc_info=True)
			print(f"[ESCL] Error: {e}", file=sys.stderr, flush=True)
			errors.append(str(e))
		finally:
			# Cleanup job (respecting SKIP_CLEANUP quirk)
			if job_url:
				await self._cleanup_job(job_url)
			self._current_job_url = None

		logger.warning(f"[ESCL] Scan failed with errors: {errors}")
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
		import sys
		print(f"=" * 60, file=sys.stderr, flush=True)
		print(f"[_create_scan_job] ENTERING", file=sys.stderr, flush=True)
		print(f"[_create_scan_job] self._host='{self._host}'", file=sys.stderr, flush=True)
		print(f"[_create_scan_job] self._port={self._port}", file=sys.stderr, flush=True)
		print(f"[_create_scan_job] self._base_url='{self._base_url}'", file=sys.stderr, flush=True)
		print(f"=" * 60, file=sys.stderr, flush=True)

		# CRITICAL: Validate host is not empty
		if not self._host:
			raise ValueError(f"[ESCL] FATAL: self._host is empty! Cannot create scan job. base_url={self._base_url}")

		# Build scan settings XML
		scan_settings = self._build_scan_settings(options)
		logger.info(f"Creating scan job at {self._base_url}/ScanJobs")
		logger.debug(f"Scan settings XML:\n{scan_settings}")

		# Retry logic for busy scanner (503 errors)
		max_retries = 10
		retry_delay = 2.0

		for attempt in range(max_retries):
			response = await self._client.post(
				f"{self._base_url}/ScanJobs",
				content=scan_settings,
				headers={'Content-Type': 'application/xml'},
			)

			logger.info(f"Scan job creation response: {response.status_code} (attempt {attempt + 1})")
			logger.debug(f"Response headers: {dict(response.headers)}")

			if response.status_code == 201:
				# Job created, get location directly from header
				raw_location = response.headers.get('Location')
				print(f"[_create_scan_job] RAW Location header: '{raw_location}'", file=sys.stderr, flush=True)
				print(f"[_create_scan_job] All response headers: {dict(response.headers)}", file=sys.stderr, flush=True)
				logger.info(f"Location header: {raw_location}")

				if raw_location:
					# Check if it's a full URL with a valid host
					if raw_location.startswith('http'):
						# Parse to check if host is present
						parsed = urlparse(raw_location)
						print(f"[_create_scan_job] Parsed full URL: scheme='{parsed.scheme}', netloc='{parsed.netloc}', path='{parsed.path}'", file=sys.stderr, flush=True)

						if parsed.netloc and ':' not in parsed.netloc[:1]:  # Has host (not starting with :)
							# Full URL with valid host - use as-is
							job_url = raw_location
							logger.info(f"Using full job URL: {job_url}")
							print(f"[_create_scan_job] Using full job URL as-is: {job_url}", file=sys.stderr, flush=True)
						else:
							# Full URL but missing/invalid host - extract path and reconstruct
							path = parsed.path
							print(f"[_create_scan_job] Full URL has empty host, extracting path: '{path}'", file=sys.stderr, flush=True)
							job_url = f"{self._scheme}://{self._host}:80{path}"
							logger.info(f"Reconstructed job URL from invalid full URL: {job_url}")
							print(f"[_create_scan_job] Reconstructed job URL: {job_url}", file=sys.stderr, flush=True)
					else:
						# Relative URL - construct with port 80 for document retrieval
						# HP scanners use port 80 for NextDocument even if API is on 8080
						print(f"[_create_scan_job] Building URL from: scheme='{self._scheme}', host='{self._host}', location='{raw_location}'", file=sys.stderr, flush=True)
						job_url = f"{self._scheme}://{self._host}:80{raw_location}"
						logger.info(f"Constructed job URL (port 80): {job_url}")
						print(f"[_create_scan_job] Final job URL: {job_url}", file=sys.stderr, flush=True)

					return job_url

			elif response.status_code == 503:
				# Scanner busy - wait and retry
				logger.warning(f"Scanner busy (503), retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
				await asyncio.sleep(retry_delay)
				continue

			else:
				# Other error - fail immediately
				logger.error(f"Scan job creation failed with status {response.status_code}: {response.text[:500]}")
				response.raise_for_status()
				break

		raise RuntimeError(f"Failed to create scan job after {max_retries} retries - scanner may be busy")

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

		xml = f'''<?xml version="1.0"?>
<scan:ScanSettings xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">
    <pwg:Version>2.0</pwg:Version>
    <pwg:ScanRegions pwg:MustHonor="false">
        <pwg:ScanRegion>
            <pwg:Height>{int((options.height or 297) / 25.4 * 300)}</pwg:Height>
            <pwg:Width>{int((options.width or 215.9) / 25.4 * 300)}</pwg:Width>
            <pwg:XOffset>{int((options.x_offset or 0) / 25.4 * 300)}</pwg:XOffset>
            <pwg:YOffset>{int((options.y_offset or 0) / 25.4 * 300)}</pwg:YOffset>
            <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>
        </pwg:ScanRegion>
    </pwg:ScanRegions>
    <pwg:InputSource>{input_source}</pwg:InputSource>
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
		"""
		Retrieve the next scanned page with full quirks support.

		Following eSCL protocol:
		- NextDocument is a blocking call while scanner is processing
		- Returns 404 when no more pages are available (ADF empty or platen done)
		- Use 404 as the terminal condition, not job status polling
		
		Quirks supported:
		- NEXT_LOAD_DELAY: Wait between pages (Brother devices)
		- RETRY_ON_404: Retry on 404 (Xerox B205/B215)
		- RETRY_ON_410: Retry on 410 (Xerox devices)
		"""
		page_url = f"{job_url}/NextDocument"
		logger.info(f"[ESCL] Getting page {page_num} from: {page_url}")

		# Brother devices need delay between pages
		if page_num > 0 and self._quirks.has(QuirkFlag.NEXT_LOAD_DELAY):
			delay_s = self._quirks.next_load_delay_ms / 1000
			logger.info(f"[ESCL] Applying NEXT_LOAD_DELAY: {delay_s}s")
			await asyncio.sleep(delay_s)

		max_wait = 120  # seconds
		poll_interval = 2.0
		elapsed = 0
		retry_404_count = 0
		retry_410_count = 0
		max_status_retries = self._quirks.retry_count

		while elapsed < max_wait:
			try:
				# Use a fresh client for document retrieval with quirk headers
				async with httpx.AsyncClient(
					timeout=60.0,
					follow_redirects=True,
					headers=self._get_request_headers()
				) as client:
					response = await client.get(page_url)
					status = response.status_code
					logger.info(f"[ESCL] NextDocument response: {status}, content-type: {response.headers.get('content-type')}")

					if status == 200:
						# Page retrieved successfully
						content_length = len(response.content)
						logger.info(f"[ESCL] Successfully retrieved page {page_num}, size: {content_length} bytes")
						return response.content

					elif status == 404:
						# Check if we should retry on 404 (Xerox quirk)
						if self._quirks.has(QuirkFlag.RETRY_ON_404) and retry_404_count < max_status_retries:
							retry_404_count += 1
							logger.info(f"[ESCL] 404 - retrying (quirk): attempt {retry_404_count}/{max_status_retries}")
							await asyncio.sleep(self._quirks.retry_delay_ms / 1000)
							elapsed += self._quirks.retry_delay_ms / 1000
							continue
						# 404 is the terminal condition - no more pages
						logger.info(f"[ESCL] 404 from NextDocument - no more pages available")
						return None

					elif status == 410:
						# Check if we should retry on 410 (Xerox quirk)
						if self._quirks.has(QuirkFlag.RETRY_ON_410) and retry_410_count < max_status_retries:
							retry_410_count += 1
							logger.info(f"[ESCL] 410 - retrying (quirk): attempt {retry_410_count}/{max_status_retries}")
							await asyncio.sleep(self._quirks.retry_delay_ms / 1000)
							elapsed += self._quirks.retry_delay_ms / 1000
							continue
						# 410 Gone - resource no longer available
						logger.info(f"[ESCL] 410 from NextDocument - scan complete")
						return None

					elif status == 503:
						# Scanner busy - wait and retry
						logger.info(f"[ESCL] 503 - scanner busy, waiting {poll_interval}s...")
						await asyncio.sleep(poll_interval)
						elapsed += poll_interval

					else:
						logger.warning(f"[ESCL] Unexpected response {status}: {response.text[:200] if response.text else 'no body'}")
						await asyncio.sleep(poll_interval)
						elapsed += poll_interval

			except httpx.ConnectError as e:
				logger.error(f"[ESCL] Connection error fetching page from {page_url}: {e}")
				await asyncio.sleep(poll_interval)
				elapsed += poll_interval

			except httpx.TimeoutException as e:
				# Timeout might mean scanner is still processing - retry
				logger.warning(f"[ESCL] Timeout fetching page (scanner may still be processing): {e}")
				await asyncio.sleep(poll_interval)
				elapsed += poll_interval

			except Exception as e:
				logger.error(f"[ESCL] Error fetching page from {page_url}: {e}", exc_info=True)
				await asyncio.sleep(poll_interval)
				elapsed += poll_interval

		logger.error(f"[ESCL] Scan job timed out after {max_wait}s")
		raise TimeoutError(f"Scan job timed out after {max_wait}s")

	async def _get_job_status(self, job_url: str) -> str:
		"""Get status of a scan job."""
		logger.debug(f"Getting job status from: {job_url}")
		try:
			# Use a direct request for cross-port requests
			async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
				response = await client.get(job_url)
				logger.debug(f"Job status response: {response.status_code}")

				if response.status_code == 200:
					logger.debug(f"Job status XML:\n{response.text[:500]}")
					root = ET.fromstring(response.text)
					state = root.find('.//pwg:JobState', NAMESPACES)
					if state is not None:
						logger.info(f"Job state (pwg): {state.text}")
						return state.text
					# Try alternative element
					state = root.find('.//scan:JobState', NAMESPACES)
					if state is not None:
						logger.info(f"Job state (scan): {state.text}")
						return state.text
				logger.warning(f"Could not find job state in response, status code: {response.status_code}")
				return 'Unknown'
		except Exception as e:
			logger.error(f"Error getting job status from {job_url}: {e}", exc_info=True)
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
