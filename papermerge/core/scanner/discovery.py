# (c) Copyright Datacraft, 2026
"""Scanner discovery using mDNS/DNS-SD for eSCL devices."""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredScanner:
	"""Information about a discovered scanner."""
	name: str
	host: str
	port: int
	protocol: str  # escl, uscan, sane
	uuid: str | None = None
	manufacturer: str | None = None
	model: str | None = None
	serial: str | None = None
	root_url: str | None = None  # eSCL root path (e.g., /eSCL)
	txt_records: dict[str, str] = field(default_factory=dict)
	discovered_at: datetime = field(default_factory=datetime.now)
	last_seen: datetime = field(default_factory=datetime.now)

	@property
	def base_url(self) -> str:
		"""Get the base URL for eSCL communication."""
		scheme = 'https' if self.port == 443 else 'http'
		root = self.root_url or '/eSCL'
		return f"{scheme}://{self.host}:{self.port}{root}"

	def __hash__(self):
		return hash((self.host, self.port, self.protocol))


class ScannerDiscovery:
	"""
	Discover scanners on the network using mDNS/DNS-SD.

	Supports eSCL (_uscan._tcp, _uscans._tcp) and IPP Scan devices.
	Uses zeroconf library for mDNS discovery.
	"""

	# mDNS service types for scanner discovery
	SERVICE_TYPES = [
		'_uscan._tcp.local.',  # eSCL over HTTP
		'_uscans._tcp.local.',  # eSCL over HTTPS
		'_scanner._tcp.local.',  # Generic scanner
		'_privet._tcp.local.',  # Google Cloud Print (legacy)
	]

	def __init__(self):
		self._scanners: dict[str, DiscoveredScanner] = {}
		self._zeroconf = None
		self._browser = None
		self._callbacks: list[Callable[[DiscoveredScanner], None]] = []
		self._running = False

	async def start(self):
		"""Start scanner discovery."""
		if self._running:
			return

		try:
			from zeroconf import Zeroconf, ServiceBrowser
			from zeroconf.asyncio import AsyncZeroconf

			self._zeroconf = AsyncZeroconf()
			self._running = True

			# Create service browsers for each type
			for service_type in self.SERVICE_TYPES:
				await self._browse_service(service_type)

			logger.info("Scanner discovery started")

		except ImportError:
			logger.warning("zeroconf not installed, scanner discovery disabled")
		except Exception as e:
			logger.error(f"Failed to start scanner discovery: {e}")

	async def _browse_service(self, service_type: str):
		"""Browse for a specific service type."""
		try:
			from zeroconf import ServiceListener

			class ScannerListener(ServiceListener):
				def __init__(self, discovery: 'ScannerDiscovery'):
					self.discovery = discovery

				def add_service(self, zc, type_, name):
					asyncio.create_task(
						self.discovery._on_service_added(zc, type_, name)
					)

				def remove_service(self, zc, type_, name):
					self.discovery._on_service_removed(name)

				def update_service(self, zc, type_, name):
					asyncio.create_task(
						self.discovery._on_service_added(zc, type_, name)
					)

			listener = ScannerListener(self)
			await self._zeroconf.async_add_service_listener(
				service_type, listener
			)

		except Exception as e:
			logger.error(f"Error browsing {service_type}: {e}")

	async def _on_service_added(self, zc, service_type: str, name: str):
		"""Handle discovered service."""
		try:
			from zeroconf import ServiceInfo

			info = ServiceInfo(service_type, name)
			if await asyncio.to_thread(
				info.request, zc.zeroconf, 3000
			):
				scanner = self._parse_service_info(name, service_type, info)
				if scanner:
					self._scanners[scanner.name] = scanner
					logger.info(f"Discovered scanner: {scanner.name} at {scanner.host}")

					for callback in self._callbacks:
						try:
							callback(scanner)
						except Exception as e:
							logger.error(f"Callback error: {e}")

		except Exception as e:
			logger.error(f"Error processing service {name}: {e}")

	def _on_service_removed(self, name: str):
		"""Handle removed service."""
		if name in self._scanners:
			logger.info(f"Scanner removed: {name}")
			del self._scanners[name]

	def _parse_service_info(
		self,
		name: str,
		service_type: str,
		info
	) -> DiscoveredScanner | None:
		"""Parse ServiceInfo into DiscoveredScanner."""
		try:
			# Get addresses
			addresses = info.parsed_addresses()
			if not addresses:
				return None
			host = addresses[0]

			# Get port
			port = info.port or (443 if 's._tcp' in service_type else 80)

			# Parse TXT records
			txt_records = {}
			if info.properties:
				for key, value in info.properties.items():
					if isinstance(key, bytes):
						key = key.decode('utf-8', errors='replace')
					if isinstance(value, bytes):
						value = value.decode('utf-8', errors='replace')
					txt_records[key] = value

			# Determine protocol
			protocol = 'escl'
			if '_uscans' in service_type:
				protocol = 'escl_secure'

			return DiscoveredScanner(
				name=name.split('.')[0],  # Remove service suffix
				host=host,
				port=port,
				protocol=protocol,
				uuid=txt_records.get('UUID') or txt_records.get('uuid'),
				manufacturer=txt_records.get('mfg') or txt_records.get('manufacturer'),
				model=txt_records.get('mdl') or txt_records.get('model'),
				serial=txt_records.get('serialNumber'),
				root_url=txt_records.get('rs', '/eSCL'),
				txt_records=txt_records,
			)

		except Exception as e:
			logger.error(f"Error parsing service info: {e}")
			return None

	async def stop(self):
		"""Stop scanner discovery."""
		if not self._running:
			return

		self._running = False

		if self._zeroconf:
			await self._zeroconf.async_close()
			self._zeroconf = None

		logger.info("Scanner discovery stopped")

	def get_scanners(self) -> list[DiscoveredScanner]:
		"""Get list of discovered scanners."""
		return list(self._scanners.values())

	def get_scanner(self, name: str) -> DiscoveredScanner | None:
		"""Get a specific scanner by name."""
		return self._scanners.get(name)

	def on_scanner_found(
		self,
		callback: Callable[[DiscoveredScanner], None]
	):
		"""Register callback for when scanner is discovered."""
		self._callbacks.append(callback)

	async def scan_now(self, timeout: float = 5.0) -> list[DiscoveredScanner]:
		"""
		Perform a one-time scan for devices.

		Args:
			timeout: How long to wait for responses

		Returns:
			List of discovered scanners
		"""
		await self.start()
		await asyncio.sleep(timeout)

		scanners = self.get_scanners()
		await self.stop()

		return scanners


async def discover_sane_scanners() -> list[DiscoveredScanner]:
	"""
	Discover scanners via SANE.

	Returns:
		List of discovered SANE scanners
	"""
	scanners = []

	try:
		import sane

		sane.init()
		devices = sane.get_devices(localOnly=False)

		for device in devices:
			# device format: (name, vendor, model, type)
			device_name, vendor, model, device_type = device

			scanner = DiscoveredScanner(
				name=f"{vendor} {model}",
				host='localhost',
				port=0,
				protocol='sane',
				manufacturer=vendor,
				model=model,
				txt_records={
					'device_name': device_name,
					'device_type': device_type,
				},
			)
			scanners.append(scanner)

		sane.exit()

	except ImportError:
		logger.debug("python-sane not installed")
	except Exception as e:
		logger.error(f"Error discovering SANE devices: {e}")

	return scanners


async def discover_all_scanners(
	timeout: float = 5.0,
	include_sane: bool = True,
) -> list[DiscoveredScanner]:
	"""
	Discover all available scanners (network and local).

	Args:
		timeout: mDNS discovery timeout
		include_sane: Whether to include SANE devices

	Returns:
		Combined list of discovered scanners
	"""
	scanners = []

	# Network discovery
	discovery = ScannerDiscovery()
	network_scanners = await discovery.scan_now(timeout)
	scanners.extend(network_scanners)

	# SANE discovery
	if include_sane:
		sane_scanners = await discover_sane_scanners()
		scanners.extend(sane_scanners)

	return scanners
