# (c) Copyright Datacraft, 2026
"""WSD (Web Services for Devices) scanner implementation.

Implements the Microsoft WSD-Scan protocol for network scanners.
Reference: https://docs.microsoft.com/en-us/windows-hardware/drivers/image/web-services-for-devices
"""
import asyncio
import logging
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from xml.etree import ElementTree as ET

import httpx

from .base import Scanner, ScannerProtocol, ScanOptions, ScanResult
from .capabilities import (
	ScannerCapabilities, ColorMode, InputSource, ImageFormat,
	Resolution, ADFCapabilities, ScanArea
)
from .quirks import DeviceQuirks, QuirkFlag, detect_quirks

logger = logging.getLogger(__name__)


# WSD XML Namespaces
WSD_NS = {
	'soap': 'http://www.w3.org/2003/05/soap-envelope',
	'wsa': 'http://schemas.xmlsoap.org/ws/2004/08/addressing',
	'wsd': 'http://schemas.xmlsoap.org/ws/2005/04/discovery',
	'wscn': 'http://schemas.microsoft.com/windows/2006/08/wdp/scan',
	'wprt': 'http://schemas.microsoft.com/windows/2006/08/wdp/print',
	'wse': 'http://schemas.xmlsoap.org/ws/2004/08/eventing',
}

# WSD Actions
WSD_ACTION_GET_SCANNER_ELEMENTS = 'http://schemas.microsoft.com/windows/2006/08/wdp/scan/GetScannerElements'
WSD_ACTION_GET_SCANNER_ELEMENTS_RESPONSE = 'http://schemas.microsoft.com/windows/2006/08/wdp/scan/GetScannerElementsResponse'
WSD_ACTION_CREATE_SCAN_JOB = 'http://schemas.microsoft.com/windows/2006/08/wdp/scan/CreateScanJob'
WSD_ACTION_CREATE_SCAN_JOB_RESPONSE = 'http://schemas.microsoft.com/windows/2006/08/wdp/scan/CreateScanJobResponse'
WSD_ACTION_RETRIEVE_IMAGE = 'http://schemas.microsoft.com/windows/2006/08/wdp/scan/RetrieveImage'
WSD_ACTION_RETRIEVE_IMAGE_RESPONSE = 'http://schemas.microsoft.com/windows/2006/08/wdp/scan/RetrieveImageResponse'
WSD_ACTION_GET_JOB_ELEMENTS = 'http://schemas.microsoft.com/windows/2006/08/wdp/scan/GetJobElements'
WSD_ACTION_CANCEL_JOB = 'http://schemas.microsoft.com/windows/2006/08/wdp/scan/CancelJob'
WSD_ACTION_GET_ACTIVE_JOBS = 'http://schemas.microsoft.com/windows/2006/08/wdp/scan/GetActiveJobs'


@dataclass
class WSDJob:
	"""WSD scan job context."""
	job_id: int
	job_token: str
	document_final_parameters: dict = field(default_factory=dict)


class WSDScanner(Scanner):
	"""
	WSD (Web Services for Devices) scanner implementation.
	
	Implements the Microsoft WSD-Scan protocol for network-attached
	multifunction devices.
	"""

	protocol = ScannerProtocol.WSD

	def __init__(
		self,
		host: str,
		port: int = 80,
		device_uri: str = '',
		timeout: float = 30.0,
	):
		self._host = host
		self._port = port
		self._device_uri = device_uri or f"http://{host}:{port}/wsd/scan"
		self._timeout = timeout
		
		self._client = httpx.AsyncClient(
			timeout=timeout,
			follow_redirects=True,
		)
		
		self._capabilities: ScannerCapabilities | None = None
		self._info: dict = {}
		self._current_job: WSDJob | None = None
		
		# Device quirks
		self._quirks: DeviceQuirks = DeviceQuirks()
		self._quirks_detected: bool = False

	@property
	def id(self) -> str:
		return f"wsd://{self._host}:{self._port}"

	@property
	def name(self) -> str:
		return self._info.get('FriendlyName', f'WSD Scanner at {self._host}')

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

	def _build_soap_envelope(self, action: str, body_content: str) -> str:
		"""Build SOAP envelope for WSD request."""
		message_id = f"urn:uuid:{uuid.uuid4()}"
		return f'''<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{WSD_NS['soap']}" xmlns:wsa="{WSD_NS['wsa']}" xmlns:wscn="{WSD_NS['wscn']}">
  <soap:Header>
    <wsa:To>{self._device_uri}</wsa:To>
    <wsa:Action>{action}</wsa:Action>
    <wsa:MessageID>{message_id}</wsa:MessageID>
    <wsa:ReplyTo>
      <wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address>
    </wsa:ReplyTo>
  </soap:Header>
  <soap:Body>
    {body_content}
  </soap:Body>
</soap:Envelope>'''

	async def _send_soap_request(self, action: str, body: str) -> ET.Element:
		"""Send SOAP request and return parsed response."""
		envelope = self._build_soap_envelope(action, body)
		
		logger.debug(f"[WSD] Sending SOAP request to {self._device_uri}")
		logger.debug(f"[WSD] Action: {action}")
		
		response = await self._client.post(
			self._device_uri,
			content=envelope,
			headers={
				'Content-Type': 'application/soap+xml; charset=utf-8',
				'SOAPAction': f'"{action}"',
			}
		)
		
		# Check for SOAP fault
		response_text = response.text
		if 'fault' in response_text.lower() or 'Fault' in response_text:
			logger.error(f"[WSD] SOAP Fault received: {response_text[:500]}")
			
			# Try to extract fault message
			try:
				root = ET.fromstring(response_text)
				fault_reason = root.find('.//{http://www.w3.org/2003/05/soap-envelope}Reason')
				if fault_reason is not None:
					fault_text = fault_reason.find('.//{http://www.w3.org/2003/05/soap-envelope}Text')
					if fault_text is not None and fault_text.text:
						raise RuntimeError(f"WSD SOAP Fault: {fault_text.text}")
			except ET.ParseError:
				pass
			
			raise RuntimeError("WSD SOAP Fault")
		
		return ET.fromstring(response_text)

	async def _detect_and_apply_quirks(self) -> None:
		"""Detect device quirks from capabilities."""
		if self._quirks_detected:
			return
		
		model = self._info.get('Model', '')
		manufacturer = self._info.get('Manufacturer', '')
		
		self._quirks = detect_quirks(model, manufacturer)
		self._quirks_detected = True
		
		if self._quirks.flags:
			logger.info(f"[WSD] Detected quirks for {model}: {self._quirks}")

	async def is_available(self) -> bool:
		"""Check if scanner is available."""
		try:
			body = '''<wscn:GetScannerElementsRequest>
				<wscn:RequestedElements>
					<wscn:Name>wscn:ScannerStatus</wscn:Name>
				</wscn:RequestedElements>
			</wscn:GetScannerElementsRequest>'''
			
			root = await self._send_soap_request(WSD_ACTION_GET_SCANNER_ELEMENTS, body)
			
			# Find scanner state
			state = root.find('.//{http://schemas.microsoft.com/windows/2006/08/wdp/scan}ScannerState')
			if state is not None:
				return state.text in ('Idle', 'Processing', 'Ready')
			
			return False
			
		except Exception as e:
			logger.debug(f"[WSD] Scanner not available: {e}")
			return False

	async def get_status(self) -> dict[str, Any]:
		"""Get scanner status."""
		try:
			body = '''<wscn:GetScannerElementsRequest>
				<wscn:RequestedElements>
					<wscn:Name>wscn:ScannerStatus</wscn:Name>
				</wscn:RequestedElements>
			</wscn:GetScannerElementsRequest>'''
			
			root = await self._send_soap_request(WSD_ACTION_GET_SCANNER_ELEMENTS, body)
			
			status = {'available': True, 'protocol': 'wsd'}
			
			state = root.find('.//{http://schemas.microsoft.com/windows/2006/08/wdp/scan}ScannerState')
			if state is not None:
				status['state'] = state.text
			
			reason = root.find('.//{http://schemas.microsoft.com/windows/2006/08/wdp/scan}ScannerStateReason')
			if reason is not None:
				status['state_reason'] = reason.text
			
			# Check ADF state
			adf_state = root.find('.//{http://schemas.microsoft.com/windows/2006/08/wdp/scan}ADFState')
			if adf_state is not None:
				status['adf_state'] = adf_state.text
			
			return status
			
		except Exception as e:
			return {'available': False, 'error': str(e)}

	async def get_capabilities(self) -> ScannerCapabilities:
		"""Get scanner capabilities via WSD."""
		if self._capabilities:
			return self._capabilities

		body = '''<wscn:GetScannerElementsRequest>
			<wscn:RequestedElements>
				<wscn:Name>wscn:ScannerConfiguration</wscn:Name>
				<wscn:Name>wscn:ScannerDescription</wscn:Name>
				<wscn:Name>wscn:DefaultScanTicket</wscn:Name>
			</wscn:RequestedElements>
		</wscn:GetScannerElementsRequest>'''

		root = await self._send_soap_request(WSD_ACTION_GET_SCANNER_ELEMENTS, body)
		
		# Extract device info
		self._parse_device_info(root)
		
		# Parse capabilities
		self._capabilities = self._parse_capabilities(root)
		
		# Detect quirks
		await self._detect_and_apply_quirks()
		
		return self._capabilities

	def _parse_device_info(self, root: ET.Element) -> None:
		"""Extract device information from response."""
		# Model name
		model_name = root.find('.//{http://schemas.microsoft.com/windows/2006/08/wdp/scan}ScannerName')
		if model_name is not None and model_name.text:
			self._info['Model'] = model_name.text
			self._info['FriendlyName'] = model_name.text
		
		# Manufacturer
		manufacturer = root.find('.//{http://schemas.microsoft.com/windows/2006/08/wdp/scan}Manufacturer')
		if manufacturer is not None and manufacturer.text:
			self._info['Manufacturer'] = manufacturer.text
		
		# Serial number
		serial = root.find('.//{http://schemas.microsoft.com/windows/2006/08/wdp/scan}SerialNumber')
		if serial is not None and serial.text:
			self._info['SerialNumber'] = serial.text

	def _parse_capabilities(self, root: ET.Element) -> ScannerCapabilities:
		"""Parse WSD capabilities response."""
		data = {}
		wscn = '{http://schemas.microsoft.com/windows/2006/08/wdp/scan}'

		# Parse input sources
		sources = []
		platen = root.find(f'.//{wscn}Platen')
		if platen is not None:
			sources.append('Platen')
		
		adf = root.find(f'.//{wscn}ADF')
		if adf is not None:
			sources.append('Feeder')
			# Check duplex
			adf_front = root.find(f'.//{wscn}ADFFront')
			adf_back = root.find(f'.//{wscn}ADFBack')
			duplex_support = root.find(f'.//{wscn}ADFSupportsDuplex')
			if (adf_back is not None) or (duplex_support is not None and duplex_support.text == 'true'):
				sources.append('ADFDuplex')
		
		data['InputSources'] = sources

		# Parse resolutions
		resolutions = set()
		for res_elem in root.findall(f'.//{wscn}Resolution'):
			width = res_elem.find(f'{wscn}Width')
			height = res_elem.find(f'{wscn}Height')
			if width is not None and width.text:
				try:
					resolutions.add(int(width.text))
				except (ValueError, TypeError):
					pass
		
		# Also check discrete resolutions
		for res_elem in root.findall(f'.//{wscn}SupportedResolutions//{wscn}Entry'):
			width = res_elem.find(f'{wscn}Width')
			if width is not None and width.text:
				try:
					resolutions.add(int(width.text))
				except (ValueError, TypeError):
					pass
		
		data['Resolutions'] = sorted(resolutions) if resolutions else [150, 300, 600]

		# Parse color modes
		color_modes = []
		for mode_elem in root.findall(f'.//{wscn}ColorEntry'):
			if mode_elem.text:
				color_modes.append(mode_elem.text)
		
		# Also check ColorProcessing
		for mode_elem in root.findall(f'.//{wscn}ColorProcessing'):
			if mode_elem.text:
				color_modes.append(mode_elem.text)
		
		data['ColorModes'] = color_modes

		# Parse formats
		formats = []
		for fmt_elem in root.findall(f'.//{wscn}FormatValue'):
			if fmt_elem.text:
				formats.append(fmt_elem.text)
		
		for fmt_elem in root.findall(f'.//{wscn}Format'):
			if fmt_elem.text:
				formats.append(fmt_elem.text)
		
		data['DocumentFormats'] = formats

		# Parse scan area dimensions
		max_width = root.find(f'.//{wscn}MaxWidth')
		max_height = root.find(f'.//{wscn}MaxHeight')
		if max_width is not None and max_height is not None:
			try:
				# WSD uses 1/1000 inch units
				data['MaxWidth'] = int(max_width.text) / 1000 * 25.4  # to mm
				data['MaxHeight'] = int(max_height.text) / 1000 * 25.4  # to mm
			except (ValueError, TypeError):
				pass

		return ScannerCapabilities.from_wsd(data)

	async def scan(self, options: ScanOptions) -> ScanResult:
		"""Perform scan via WSD protocol."""
		print(f"[WSD] Starting scan: resolution={options.resolution}, format={options.format}", file=sys.stderr, flush=True)
		logger.info(f"[WSD] Starting scan with options: resolution={options.resolution}")
		
		start_time = time.time()
		pages = []
		errors = []

		try:
			# Ensure capabilities are loaded for quirks detection
			if not self._capabilities:
				await self.get_capabilities()
			
			# Create scan job
			job = await self._create_scan_job(options)
			self._current_job = job
			logger.info(f"[WSD] Scan job created: JobId={job.job_id}")
			print(f"[WSD] Job created: {job.job_id}", file=sys.stderr, flush=True)

			# Retrieve images
			page_num = 0
			while True:
				logger.info(f"[WSD] Retrieving page {page_num}...")
				page_data = await self._retrieve_image(job)
				
				if page_data is None:
					logger.info(f"[WSD] No more pages available")
					print(f"[WSD] Scan complete: {page_num} pages", file=sys.stderr, flush=True)
					break
				
				logger.info(f"[WSD] Got page {page_num}, size: {len(page_data)} bytes")
				print(f"[WSD] Got page {page_num}: {len(page_data)} bytes", file=sys.stderr, flush=True)
				pages.append(page_data)
				page_num += 1

				# For platen, only one page
				if options.input_source == 'platen':
					break

				if options.max_pages and page_num >= options.max_pages:
					logger.info(f"[WSD] Reached max_pages limit: {options.max_pages}")
					break

			scan_time = (time.time() - start_time) * 1000
			logger.info(f"[WSD] Scan completed: {len(pages)} pages in {scan_time:.0f}ms")
			print(f"[WSD] SUCCESS: {len(pages)} pages in {scan_time:.0f}ms", file=sys.stderr, flush=True)
			
			return ScanResult(
				success=True,
				pages=pages,
				page_count=len(pages),
				format=options.format,
				scan_time_ms=scan_time,
			)

		except Exception as e:
			logger.error(f"[WSD] Scan failed: {e}", exc_info=True)
			print(f"[WSD] Error: {e}", file=sys.stderr, flush=True)
			errors.append(str(e))
			
			return ScanResult(
				success=False,
				pages=pages,
				page_count=len(pages),
				format=options.format,
				scan_time_ms=(time.time() - start_time) * 1000,
				errors=errors,
			)
		finally:
			self._current_job = None

	async def scan_stream(self, options: ScanOptions) -> AsyncIterator[tuple[int, bytes]]:
		"""Stream scanned pages as they complete."""
		# Ensure capabilities are loaded
		if not self._capabilities:
			await self.get_capabilities()
		
		job = await self._create_scan_job(options)
		self._current_job = job

		try:
			page_num = 0
			while True:
				page_data = await self._retrieve_image(job)
				if page_data is None:
					break

				yield (page_num, page_data)
				page_num += 1

				if options.input_source == 'platen':
					break

				if options.max_pages and page_num >= options.max_pages:
					break
		finally:
			self._current_job = None

	async def _create_scan_job(self, options: ScanOptions) -> WSDJob:
		"""Create WSD scan job."""
		# Map color mode
		color_map = {
			'color': 'RGB24',
			'grayscale': 'Grayscale8',
			'monochrome': 'BlackAndWhite1',
		}
		color = color_map.get(options.color_mode, 'RGB24')

		# Map input source
		source_map = {
			'platen': 'Platen',
			'adf': 'ADFFront',
			'adf_duplex': 'ADFDuplex',
		}
		source = source_map.get(options.input_source, 'Platen')
		
		# Handle duplex
		if options.duplex and options.input_source == 'adf':
			source = 'ADFDuplex'

		# Map format
		format_map = {
			'jpeg': 'jfif',
			'png': 'png',
			'tiff': 'tiff-single-uncompressed',
			'pdf': 'pdf-a',
		}
		doc_format = format_map.get(options.format, 'jfif')

		# ImagesToTransfer: 0 means unlimited, but Ricoh devices need 100
		images_to_transfer = 0
		if self._quirks.has(QuirkFlag.WSD_IMAGES_TO_TRANSFER):
			images_to_transfer = 100
			logger.info(f"[WSD] Applying WSD_IMAGES_TO_TRANSFER quirk: {images_to_transfer}")

		# Width/Height handling for Kyocera
		width = int((options.width or 215.9) / 25.4 * 1000)  # mm to 1/1000 inch
		height = int((options.height or 297) / 25.4 * 1000)
		
		if self._quirks.has(QuirkFlag.WSD_SWAP_WIDTH_HEIGHT):
			width, height = height, width
			logger.info(f"[WSD] Applying WSD_SWAP_WIDTH_HEIGHT quirk")

		body = f'''<wscn:CreateScanJobRequest>
			<wscn:ScanTicket>
				<wscn:JobDescription>
					<wscn:JobName>dArchiva Scan Job</wscn:JobName>
					<wscn:JobOriginatingUserName>dArchiva</wscn:JobOriginatingUserName>
				</wscn:JobDescription>
				<wscn:DocumentParameters>
					<wscn:Format>{doc_format}</wscn:Format>
					<wscn:ImagesToTransfer>{images_to_transfer}</wscn:ImagesToTransfer>
					<wscn:InputSource>{source}</wscn:InputSource>
					<wscn:InputSize>
						<wscn:DocumentSizeAutoDetect>true</wscn:DocumentSizeAutoDetect>
					</wscn:InputSize>
					<wscn:Scaling>
						<wscn:ScalingWidth>{options.resolution}</wscn:ScalingWidth>
						<wscn:ScalingHeight>{options.resolution}</wscn:ScalingHeight>
					</wscn:Scaling>
					<wscn:MediaSides>
						<wscn:MediaFront>
							<wscn:ColorProcessing>{color}</wscn:ColorProcessing>
							<wscn:Resolution>
								<wscn:Width>{options.resolution}</wscn:Width>
								<wscn:Height>{options.resolution}</wscn:Height>
							</wscn:Resolution>
						</wscn:MediaFront>
					</wscn:MediaSides>
				</wscn:DocumentParameters>
			</wscn:ScanTicket>
		</wscn:CreateScanJobRequest>'''

		root = await self._send_soap_request(WSD_ACTION_CREATE_SCAN_JOB, body)
		wscn = '{http://schemas.microsoft.com/windows/2006/08/wdp/scan}'

		job_id_elem = root.find(f'.//{wscn}JobId')
		job_token_elem = root.find(f'.//{wscn}JobToken')

		if job_id_elem is None or job_token_elem is None:
			raise RuntimeError("Failed to create WSD scan job - missing JobId or JobToken")

		return WSDJob(
			job_id=int(job_id_elem.text),
			job_token=job_token_elem.text,
			document_final_parameters={},
		)

	async def _retrieve_image(self, job: WSDJob) -> bytes | None:
		"""Retrieve image from WSD scan job."""
		body = f'''<wscn:RetrieveImageRequest>
			<wscn:JobId>{job.job_id}</wscn:JobId>
			<wscn:JobToken>{job.job_token}</wscn:JobToken>
			<wscn:DocumentDescription>
				<wscn:DocumentName>Scan</wscn:DocumentName>
			</wscn:DocumentDescription>
		</wscn:RetrieveImageRequest>'''

		envelope = self._build_soap_envelope(WSD_ACTION_RETRIEVE_IMAGE, body)

		response = await self._client.post(
			self._device_uri,
			content=envelope,
			headers={
				'Content-Type': 'application/soap+xml; charset=utf-8',
				'SOAPAction': f'"{WSD_ACTION_RETRIEVE_IMAGE}"',
			}
		)

		# Check for "no images available" fault
		response_text = response.text
		if 'ClientErrorNoImagesAvailable' in response_text:
			logger.info("[WSD] No more images available (ClientErrorNoImagesAvailable)")
			return None
		
		if 'ServerErrorJobCancelled' in response_text:
			logger.info("[WSD] Job was cancelled")
			return None
		
		if 'ClientErrorJobIdNotFound' in response_text:
			logger.warning("[WSD] Job not found - may have completed")
			return None

		# Check content type for multipart
		content_type = response.headers.get('content-type', '')
		
		if 'multipart' in content_type:
			# Parse multipart response
			return self._extract_image_from_multipart(response.content, content_type)
		
		elif 'image/' in content_type or 'application/octet-stream' in content_type:
			# Direct image response
			return response.content
		
		elif 'application/soap+xml' in content_type:
			# SOAP response - check if it contains image data
			# Some devices embed base64 image in SOAP response
			root = ET.fromstring(response_text)
			wscn = '{http://schemas.microsoft.com/windows/2006/08/wdp/scan}'
			image_data = root.find(f'.//{wscn}ImageData')
			if image_data is not None and image_data.text:
				import base64
				return base64.b64decode(image_data.text)
			
			# Check for completion
			scan_available = root.find(f'.//{wscn}ScanAvailableEvent')
			if scan_available is None:
				# No more images
				return None
		
		logger.warning(f"[WSD] Unexpected content type: {content_type}")
		return None

	def _extract_image_from_multipart(self, content: bytes, content_type: str) -> bytes | None:
		"""Extract image data from multipart MIME response."""
		# Find boundary from content-type header
		boundary_match = re.search(r'boundary=([^;\s]+)', content_type)
		if not boundary_match:
			logger.warning("[WSD] Could not find boundary in multipart response")
			return None

		boundary = boundary_match.group(1).strip('"').encode()
		parts = content.split(b'--' + boundary)

		# Image is typically the second part (after SOAP envelope)
		for part in parts[1:]:
			# Skip if it's the closing boundary
			if part.strip() == b'--' or not part.strip():
				continue
			
			# Check for image content type in headers
			if b'Content-Type: image/' in part or b'application/octet-stream' in part:
				# Find start of binary data (after headers)
				header_end = part.find(b'\r\n\r\n')
				if header_end != -1:
					image_data = part[header_end + 4:]
					# Remove trailing boundary markers
					if image_data.endswith(b'--\r\n'):
						image_data = image_data[:-4]
					elif image_data.endswith(b'\r\n'):
						image_data = image_data[:-2]
					return image_data
			
			# Some devices put image data in XOP package
			if b'Content-Transfer-Encoding: binary' in part:
				header_end = part.find(b'\r\n\r\n')
				if header_end != -1:
					return part[header_end + 4:].rstrip(b'-\r\n')

		logger.warning("[WSD] Could not find image data in multipart response")
		return None

	async def cancel_scan(self) -> bool:
		"""Cancel current scan job."""
		if not self._current_job:
			return False

		try:
			body = f'''<wscn:CancelJobRequest>
				<wscn:JobId>{self._current_job.job_id}</wscn:JobId>
			</wscn:CancelJobRequest>'''

			await self._send_soap_request(WSD_ACTION_CANCEL_JOB, body)
			logger.info(f"[WSD] Job {self._current_job.job_id} cancelled")
			return True
			
		except Exception as e:
			logger.warning(f"[WSD] Failed to cancel job: {e}")
			return False
