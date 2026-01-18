# (c) Copyright Datacraft, 2026
"""Scanner management service with robust discovery and device control."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.scanner.base import Scanner, ScanOptions, ScanResult, ScanJobStatus as BaseScanJobStatus
from papermerge.core.scanner.escl import ESCLScanner
from papermerge.core.scanner.sane import SANEScanner
from papermerge.core.scanner.discovery import (
	ScannerDiscovery,
	DiscoveredScanner,
	discover_all_scanners,
	discover_sane_scanners,
)
from papermerge.core.scanner.capabilities import ScannerCapabilities

from .models import ScannerModel, ScanJobModel, ScanProfileModel, ScannerSettingsModel
from .views import (
	ScannerCreate,
	ScannerUpdate,
	ScannerResponse,
	ScannerStatusResponse,
	ScannerCapabilitiesResponse,
	DiscoveredScannerResponse,
	ScanJobCreate,
	ScanJobResponse,
	ScanJobResultResponse,
	ScanProfileCreate,
	ScanProfileUpdate,
	ScanProfileResponse,
	GlobalScannerSettingsUpdate,
	GlobalScannerSettingsResponse,
	ScannerUsageStats,
	ScannerDashboard,
	ScannerStatus,
	ScanJobStatus,
	ScanOptionsBase,
)

logger = logging.getLogger(__name__)


# === Discovery Service ===

class ScannerDiscoveryService:
	"""Robust scanner discovery with retries and caching."""

	def __init__(self):
		self._discovery = ScannerDiscovery()
		self._cache: dict[str, DiscoveredScanner] = {}
		self._cache_expires: datetime | None = None
		self._lock = asyncio.Lock()

	async def discover_network_scanners(
		self,
		timeout: float = 8.0,
		force_refresh: bool = False,
	) -> list[DiscoveredScanner]:
		"""
		Discover eSCL/AirScan scanners on the network.

		Uses mDNS with retries and result caching for reliability.
		"""
		async with self._lock:
			# Return cached results if fresh
			if not force_refresh and self._cache and self._cache_expires:
				if datetime.now() < self._cache_expires:
					return list(self._cache.values())

			scanners: dict[str, DiscoveredScanner] = {}
			retry_count = 3
			retry_delay = 1.0

			for attempt in range(retry_count):
				try:
					await self._discovery.start()
					await asyncio.sleep(timeout / retry_count)

					for scanner in self._discovery.get_scanners():
						# Deduplicate by host:port
						key = f"{scanner.host}:{scanner.port}"
						if key not in scanners:
							# Validate scanner is reachable
							if await self._validate_escl_scanner(scanner):
								scanners[key] = scanner

					await self._discovery.stop()

				except Exception as e:
					logger.warning(f"Discovery attempt {attempt + 1} failed: {e}")
					await asyncio.sleep(retry_delay)
					retry_delay *= 2  # Exponential backoff

			# Update cache
			self._cache = scanners
			self._cache_expires = datetime.now() + timedelta(minutes=5)

			return list(scanners.values())

	async def _validate_escl_scanner(
		self,
		scanner: DiscoveredScanner,
		timeout: float = 3.0,
	) -> bool:
		"""Validate that an eSCL scanner is actually reachable."""
		try:
			async with ESCLScanner(
				host=scanner.host,
				port=scanner.port,
				root_path=scanner.root_url or '/eSCL',
				timeout=timeout,
			) as escl:
				return await escl.is_available()
		except Exception as e:
			logger.debug(f"Scanner validation failed for {scanner.name}: {e}")
			return False

	async def discover_local_scanners(self) -> list[DiscoveredScanner]:
		"""Discover local SANE scanners."""
		try:
			return await discover_sane_scanners()
		except Exception as e:
			logger.error(f"SANE discovery error: {e}")
			return []

	async def discover_all(
		self,
		timeout: float = 8.0,
		include_sane: bool = True,
		force_refresh: bool = False,
	) -> list[DiscoveredScanner]:
		"""Discover all available scanners."""
		tasks = [self.discover_network_scanners(timeout, force_refresh)]
		if include_sane:
			tasks.append(self.discover_local_scanners())

		results = await asyncio.gather(*tasks, return_exceptions=True)

		scanners = []
		for result in results:
			if isinstance(result, list):
				scanners.extend(result)
			elif isinstance(result, Exception):
				logger.error(f"Discovery error: {result}")

		return scanners


# Global discovery service instance
_discovery_service = ScannerDiscoveryService()


async def discover_scanners(
	timeout: float = 8.0,
	include_sane: bool = True,
	force_refresh: bool = False,
) -> list[DiscoveredScannerResponse]:
	"""Discover all available scanners."""
	discovered = await _discovery_service.discover_all(timeout, include_sane, force_refresh)
	return [
		DiscoveredScannerResponse(
			name=s.name,
			host=s.host,
			port=s.port,
			protocol=s.protocol,
			uuid=s.uuid,
			manufacturer=s.manufacturer,
			model=s.model,
			serial=s.serial,
			root_url=s.root_url,
			discovered_at=s.discovered_at,
		)
		for s in discovered
	]


# === Scanner Device Management ===

async def get_scanner_instance(scanner: ScannerModel) -> Scanner:
	"""Create a scanner instance from database model."""
	if scanner.protocol == 'escl':
		# Parse connection URI: escl://host:port/path
		uri = scanner.connection_uri
		if uri.startswith('escl://'):
			uri = uri[7:]
		parts = uri.split('/', 1)
		host_port = parts[0].split(':')
		host = host_port[0]
		port = int(host_port[1]) if len(host_port) > 1 else 80
		path = '/' + parts[1] if len(parts) > 1 else '/eSCL'

		return ESCLScanner(host=host, port=port, root_path=path)

	elif scanner.protocol == 'sane':
		# Parse connection URI: sane://device_name
		device_name = scanner.connection_uri
		if device_name.startswith('sane://'):
			device_name = device_name[7:]
		return SANEScanner(device_name=device_name)

	else:
		raise ValueError(f"Unsupported protocol: {scanner.protocol}")


async def get_scanners(
	session: AsyncSession,
	tenant_id: str,
	active_only: bool = True,
) -> list[ScannerResponse]:
	"""Get all registered scanners for tenant."""
	query = select(ScannerModel).where(ScannerModel.tenant_id == tenant_id)
	if active_only:
		query = query.where(ScannerModel.is_active == True)
	query = query.order_by(ScannerModel.is_default.desc(), ScannerModel.name)

	result = await session.execute(query)
	scanners = result.scalars().all()

	return [_scanner_to_response(s) for s in scanners]


async def get_scanner(
	session: AsyncSession,
	tenant_id: str,
	scanner_id: str,
) -> ScannerResponse | None:
	"""Get a specific scanner."""
	result = await session.execute(
		select(ScannerModel).where(
			ScannerModel.id == scanner_id,
			ScannerModel.tenant_id == tenant_id,
		)
	)
	scanner = result.scalar_one_or_none()
	return _scanner_to_response(scanner) if scanner else None


async def create_scanner(
	session: AsyncSession,
	tenant_id: str,
	data: ScannerCreate,
) -> ScannerResponse:
	"""Register a new scanner."""
	# If this is default, unset other defaults
	if data.is_default:
		await session.execute(
			update(ScannerModel)
			.where(ScannerModel.tenant_id == tenant_id)
			.values(is_default=False)
		)

	scanner = ScannerModel(
		tenant_id=tenant_id,
		name=data.name,
		protocol=data.protocol.value,
		connection_uri=data.connection_uri,
		location_id=data.location_id,
		is_default=data.is_default,
		is_active=data.is_active,
		notes=data.notes,
	)
	session.add(scanner)
	await session.flush()

	# Try to fetch capabilities
	try:
		instance = await get_scanner_instance(scanner)
		async with instance:
			caps = await instance.get_capabilities()
			scanner.capabilities = _capabilities_to_dict(caps)
			scanner.manufacturer = instance.manufacturer
			scanner.model = instance.model
			if await instance.is_available():
				scanner.status = 'online'
				scanner.last_seen_at = datetime.now()
	except Exception as e:
		logger.warning(f"Could not fetch scanner capabilities: {e}")

	await session.commit()
	return _scanner_to_response(scanner)


async def update_scanner(
	session: AsyncSession,
	tenant_id: str,
	scanner_id: str,
	data: ScannerUpdate,
) -> ScannerResponse | None:
	"""Update scanner settings."""
	result = await session.execute(
		select(ScannerModel).where(
			ScannerModel.id == scanner_id,
			ScannerModel.tenant_id == tenant_id,
		)
	)
	scanner = result.scalar_one_or_none()
	if not scanner:
		return None

	# If setting as default, unset others
	if data.is_default:
		await session.execute(
			update(ScannerModel)
			.where(ScannerModel.tenant_id == tenant_id, ScannerModel.id != scanner_id)
			.values(is_default=False)
		)

	for field, value in data.model_dump(exclude_unset=True).items():
		setattr(scanner, field, value)

	scanner.updated_at = datetime.now()
	await session.commit()
	return _scanner_to_response(scanner)


async def delete_scanner(
	session: AsyncSession,
	tenant_id: str,
	scanner_id: str,
) -> bool:
	"""Delete a scanner registration."""
	result = await session.execute(
		delete(ScannerModel).where(
			ScannerModel.id == scanner_id,
			ScannerModel.tenant_id == tenant_id,
		)
	)
	await session.commit()
	return result.rowcount > 0


async def get_scanner_status(
	session: AsyncSession,
	tenant_id: str,
	scanner_id: str,
) -> ScannerStatusResponse | None:
	"""Get real-time scanner status."""
	result = await session.execute(
		select(ScannerModel).where(
			ScannerModel.id == scanner_id,
			ScannerModel.tenant_id == tenant_id,
		)
	)
	scanner = result.scalar_one_or_none()
	if not scanner:
		return None

	try:
		instance = await get_scanner_instance(scanner)
		async with instance:
			status = await instance.get_status()

			# Update scanner record
			scanner.status = 'online' if status.get('available') else 'offline'
			scanner.last_seen_at = datetime.now()
			await session.commit()

			return ScannerStatusResponse(
				scanner_id=scanner.id,
				status=ScannerStatus(scanner.status) if status.get('available') else ScannerStatus.OFFLINE,
				available=status.get('available', False),
				state=status.get('state'),
				adf_state=status.get('adf_state'),
				active_jobs=status.get('active_jobs', 0),
				last_checked=datetime.now(),
			)

	except Exception as e:
		scanner.status = 'error'
		scanner.last_error = str(e)
		await session.commit()

		return ScannerStatusResponse(
			scanner_id=scanner.id,
			status=ScannerStatus.ERROR,
			available=False,
			error=str(e),
			last_checked=datetime.now(),
		)


async def refresh_scanner_capabilities(
	session: AsyncSession,
	tenant_id: str,
	scanner_id: str,
) -> ScannerCapabilitiesResponse | None:
	"""Refresh and return scanner capabilities."""
	result = await session.execute(
		select(ScannerModel).where(
			ScannerModel.id == scanner_id,
			ScannerModel.tenant_id == tenant_id,
		)
	)
	scanner = result.scalar_one_or_none()
	if not scanner:
		return None

	try:
		instance = await get_scanner_instance(scanner)
		async with instance:
			caps = await instance.get_capabilities()
			scanner.capabilities = _capabilities_to_dict(caps)
			scanner.manufacturer = instance.manufacturer
			scanner.model = instance.model
			scanner.last_seen_at = datetime.now()
			scanner.status = 'online'
			await session.commit()

			return _dict_to_capabilities_response(scanner.capabilities)

	except Exception as e:
		logger.error(f"Failed to get capabilities: {e}")
		return None


# === Scan Jobs ===

async def create_scan_job(
	session: AsyncSession,
	tenant_id: str,
	user_id: str,
	data: ScanJobCreate,
) -> ScanJobResponse:
	"""Create a new scan job."""
	job = ScanJobModel(
		tenant_id=tenant_id,
		scanner_id=data.scanner_id,
		user_id=user_id,
		status='pending',
		options=data.options.model_dump(),
		project_id=data.project_id,
		batch_id=data.batch_id,
		destination_folder_id=data.destination_folder_id,
	)
	session.add(job)
	await session.commit()

	return _job_to_response(job)


async def execute_scan_job(
	session: AsyncSession,
	tenant_id: str,
	job_id: str,
) -> ScanJobResultResponse:
	"""Execute a pending scan job."""
	result = await session.execute(
		select(ScanJobModel).where(
			ScanJobModel.id == job_id,
			ScanJobModel.tenant_id == tenant_id,
		)
	)
	job = result.scalar_one_or_none()
	if not job:
		return ScanJobResultResponse(
			job_id=job_id,
			success=False,
			pages_scanned=0,
			format='jpeg',
			scan_time_ms=0,
			errors=['Job not found'],
		)

	# Get scanner
	scanner_result = await session.execute(
		select(ScannerModel).where(ScannerModel.id == job.scanner_id)
	)
	scanner = scanner_result.scalar_one_or_none()
	if not scanner:
		job.status = 'failed'
		job.error_message = 'Scanner not found'
		await session.commit()
		return ScanJobResultResponse(
			job_id=job_id,
			success=False,
			pages_scanned=0,
			format='jpeg',
			scan_time_ms=0,
			errors=['Scanner not found'],
		)

	# Execute scan
	job.status = 'scanning'
	job.started_at = datetime.now()
	await session.commit()

	try:
		instance = await get_scanner_instance(scanner)
		options = ScanOptions(**job.options)

		async with instance:
			scan_result = await instance.scan(options)

		if scan_result.success:
			job.status = 'completed'
			job.pages_scanned = scan_result.page_count
			job.scan_time_ms = scan_result.scan_time_ms

			# Update scanner stats
			scanner.total_pages_scanned += scan_result.page_count
			scanner.total_jobs += 1
			scanner.last_seen_at = datetime.now()

			# TODO: Create documents from scanned pages

		else:
			job.status = 'failed'
			job.error_message = '; '.join(scan_result.errors)

		job.completed_at = datetime.now()
		await session.commit()

		return ScanJobResultResponse(
			job_id=job_id,
			success=scan_result.success,
			pages_scanned=scan_result.page_count,
			format=scan_result.format,
			scan_time_ms=scan_result.scan_time_ms,
			document_ids=job.document_ids or [],
			errors=scan_result.errors,
		)

	except Exception as e:
		job.status = 'failed'
		job.error_message = str(e)
		job.completed_at = datetime.now()
		await session.commit()

		return ScanJobResultResponse(
			job_id=job_id,
			success=False,
			pages_scanned=0,
			format='jpeg',
			scan_time_ms=0,
			errors=[str(e)],
		)


async def cancel_scan_job(
	session: AsyncSession,
	tenant_id: str,
	job_id: str,
) -> bool:
	"""Cancel a running scan job."""
	result = await session.execute(
		select(ScanJobModel).where(
			ScanJobModel.id == job_id,
			ScanJobModel.tenant_id == tenant_id,
			ScanJobModel.status.in_(['pending', 'scanning']),
		)
	)
	job = result.scalar_one_or_none()
	if not job:
		return False

	# If scanning, try to cancel on device
	if job.status == 'scanning':
		scanner_result = await session.execute(
			select(ScannerModel).where(ScannerModel.id == job.scanner_id)
		)
		scanner = scanner_result.scalar_one_or_none()
		if scanner:
			try:
				instance = await get_scanner_instance(scanner)
				async with instance:
					await instance.cancel_scan()
			except Exception as e:
				logger.warning(f"Could not cancel scan on device: {e}")

	job.status = 'cancelled'
	job.completed_at = datetime.now()
	await session.commit()
	return True


async def get_scan_jobs(
	session: AsyncSession,
	tenant_id: str,
	scanner_id: str | None = None,
	status: str | None = None,
	limit: int = 50,
) -> list[ScanJobResponse]:
	"""Get scan jobs."""
	query = select(ScanJobModel).where(ScanJobModel.tenant_id == tenant_id)
	if scanner_id:
		query = query.where(ScanJobModel.scanner_id == scanner_id)
	if status:
		query = query.where(ScanJobModel.status == status)
	query = query.order_by(ScanJobModel.created_at.desc()).limit(limit)

	result = await session.execute(query)
	jobs = result.scalars().all()
	return [_job_to_response(j) for j in jobs]


# === Scan Profiles ===

async def get_scan_profiles(
	session: AsyncSession,
	tenant_id: str,
) -> list[ScanProfileResponse]:
	"""Get all scan profiles."""
	result = await session.execute(
		select(ScanProfileModel)
		.where(ScanProfileModel.tenant_id == tenant_id)
		.order_by(ScanProfileModel.is_default.desc(), ScanProfileModel.name)
	)
	profiles = result.scalars().all()
	return [_profile_to_response(p) for p in profiles]


async def create_scan_profile(
	session: AsyncSession,
	tenant_id: str,
	user_id: str,
	data: ScanProfileCreate,
) -> ScanProfileResponse:
	"""Create a scan profile."""
	if data.is_default:
		await session.execute(
			update(ScanProfileModel)
			.where(ScanProfileModel.tenant_id == tenant_id)
			.values(is_default=False)
		)

	profile = ScanProfileModel(
		tenant_id=tenant_id,
		created_by_id=user_id,
		name=data.name,
		description=data.description,
		is_default=data.is_default,
		options=data.options.model_dump(),
	)
	session.add(profile)
	await session.commit()
	return _profile_to_response(profile)


# === Dashboard ===

async def get_scanner_dashboard(
	session: AsyncSession,
	tenant_id: str,
) -> ScannerDashboard:
	"""Get scanner dashboard data."""
	# Get all scanners
	scanners_result = await session.execute(
		select(ScannerModel).where(ScannerModel.tenant_id == tenant_id)
	)
	scanners = scanners_result.scalars().all()

	# Count by status
	online = sum(1 for s in scanners if s.status == 'online')
	offline = sum(1 for s in scanners if s.status == 'offline')
	busy = sum(1 for s in scanners if s.status == 'busy')

	# Get today's stats
	today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
	jobs_result = await session.execute(
		select(ScanJobModel).where(
			ScanJobModel.tenant_id == tenant_id,
			ScanJobModel.created_at >= today,
		)
	)
	jobs_today = jobs_result.scalars().all()
	pages_today = sum(j.pages_scanned for j in jobs_today)

	# Recent jobs
	recent_result = await session.execute(
		select(ScanJobModel)
		.where(ScanJobModel.tenant_id == tenant_id)
		.order_by(ScanJobModel.created_at.desc())
		.limit(10)
	)
	recent_jobs = recent_result.scalars().all()

	# Usage stats per scanner
	usage_stats = []
	for scanner in scanners:
		jobs_result = await session.execute(
			select(ScanJobModel).where(ScanJobModel.scanner_id == scanner.id)
		)
		scanner_jobs = jobs_result.scalars().all()
		total_jobs = len(scanner_jobs)
		successful = sum(1 for j in scanner_jobs if j.status == 'completed')
		failed = sum(1 for j in scanner_jobs if j.status == 'failed')
		total_pages = sum(j.pages_scanned for j in scanner_jobs)
		avg_pages = total_pages / total_jobs if total_jobs > 0 else 0
		avg_time = sum(j.scan_time_ms or 0 for j in scanner_jobs) / total_jobs if total_jobs > 0 else 0

		usage_stats.append(ScannerUsageStats(
			scanner_id=scanner.id,
			scanner_name=scanner.name,
			total_jobs=total_jobs,
			total_pages=total_pages,
			successful_jobs=successful,
			failed_jobs=failed,
			average_pages_per_job=avg_pages,
			average_scan_time_ms=avg_time,
			uptime_percentage=100 if scanner.status == 'online' else 0,
		))

	return ScannerDashboard(
		total_scanners=len(scanners),
		online_scanners=online,
		offline_scanners=offline,
		busy_scanners=busy,
		total_pages_today=pages_today,
		total_jobs_today=len(jobs_today),
		scanners=[_scanner_to_response(s) for s in scanners],
		recent_jobs=[_job_to_response(j) for j in recent_jobs],
		usage_stats=usage_stats,
	)


# === Helper Functions ===

def _scanner_to_response(scanner: ScannerModel) -> ScannerResponse:
	return ScannerResponse(
		id=scanner.id,
		tenant_id=scanner.tenant_id,
		name=scanner.name,
		protocol=scanner.protocol,
		connection_uri=scanner.connection_uri,
		manufacturer=scanner.manufacturer,
		model=scanner.model,
		serial_number=scanner.serial_number,
		firmware_version=scanner.firmware_version,
		status=ScannerStatus(scanner.status),
		last_seen_at=scanner.last_seen_at,
		location_id=scanner.location_id,
		is_default=scanner.is_default,
		is_active=scanner.is_active,
		notes=scanner.notes,
		total_pages_scanned=scanner.total_pages_scanned,
		capabilities=_dict_to_capabilities_response(scanner.capabilities) if scanner.capabilities else None,
		created_at=scanner.created_at,
		updated_at=scanner.updated_at,
	)


def _job_to_response(job: ScanJobModel) -> ScanJobResponse:
	return ScanJobResponse(
		id=job.id,
		scanner_id=job.scanner_id,
		user_id=job.user_id,
		status=ScanJobStatus(job.status),
		options=ScanOptionsBase(**job.options),
		pages_scanned=job.pages_scanned,
		project_id=job.project_id,
		batch_id=job.batch_id,
		destination_folder_id=job.destination_folder_id,
		error_message=job.error_message,
		created_at=job.created_at,
		started_at=job.started_at,
		completed_at=job.completed_at,
	)


def _profile_to_response(profile: ScanProfileModel) -> ScanProfileResponse:
	return ScanProfileResponse(
		id=profile.id,
		tenant_id=profile.tenant_id,
		created_by_id=profile.created_by_id,
		name=profile.name,
		description=profile.description,
		is_default=profile.is_default,
		options=ScanOptionsBase(**profile.options),
		created_at=profile.created_at,
		updated_at=profile.updated_at,
	)


def _capabilities_to_dict(caps: ScannerCapabilities) -> dict:
	return {
		'platen': caps.platen,
		'adf_present': caps.adf.present,
		'adf_duplex': caps.adf.duplex,
		'adf_capacity': caps.adf.capacity,
		'resolutions': caps.resolution.discrete_values or [caps.resolution.min_dpi, caps.resolution.default_dpi, caps.resolution.max_dpi],
		'color_modes': [m.value for m in caps.color_modes],
		'formats': [f.value for f in caps.formats],
		'max_width_mm': caps.platen_area.max_x,
		'max_height_mm': caps.platen_area.max_y,
		'auto_crop': caps.auto_crop,
		'auto_deskew': caps.auto_deskew,
		'blank_page_removal': caps.blank_page_removal,
		'brightness_control': caps.brightness_control,
		'contrast_control': caps.contrast_control,
	}


def _dict_to_capabilities_response(data: dict) -> ScannerCapabilitiesResponse:
	from .views import ColorMode, ImageFormat
	return ScannerCapabilitiesResponse(
		platen=data.get('platen', True),
		adf_present=data.get('adf_present', False),
		adf_duplex=data.get('adf_duplex', False),
		adf_capacity=data.get('adf_capacity', 0),
		resolutions=data.get('resolutions', [150, 300, 600]),
		color_modes=[ColorMode(m) for m in data.get('color_modes', ['color', 'grayscale'])],
		formats=[ImageFormat(f) for f in data.get('formats', ['jpeg', 'png'])],
		max_width_mm=data.get('max_width_mm', 215.9),
		max_height_mm=data.get('max_height_mm', 355.6),
		auto_crop=data.get('auto_crop', False),
		auto_deskew=data.get('auto_deskew', False),
		blank_page_removal=data.get('blank_page_removal', False),
		brightness_control=data.get('brightness_control', True),
		contrast_control=data.get('contrast_control', True),
	)
