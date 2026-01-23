# (c) Copyright Datacraft, 2026
"""Device quirks database for eSCL and WSD scanners.

This module contains known device-specific workarounds derived from
the sane-airscan project and other scanner compatibility research.
"""
from dataclasses import dataclass, field
from enum import Enum, auto


class QuirkFlag(Enum):
	"""All known device quirks from sane-airscan and similar projects."""
	# HTTP Header Quirks
	LOCALHOST_HEADER = auto()      # HP: Force Host header to "localhost"
	PORT_IN_HOST = auto()          # EPSON: Include port in Host header
	
	# ADF/Input Quirks
	CHECK_ADF_STATE = auto()       # Canon MF410, Xerox 3345: Validate ADF before scan
	
	# Timing Quirks
	NEXT_LOAD_DELAY = auto()       # Brother: Delay between LOAD requests
	
	# Retry Quirks
	RETRY_ON_404 = auto()          # Xerox B205/B215: Retry on 404
	RETRY_ON_410 = auto()          # Xerox B205/B215, WorkCentre 3345: Retry on 410
	
	# Protocol Quirks
	BROKEN_IPV6_LOCATION = auto()  # Xerox B205/B215: Fix IPv6 in Location header
	SKIP_CLEANUP = auto()          # Xerox B205/B215: Skip DELETE after scan
	
	# Resolution Quirks
	CAP_RESOLUTION_300 = auto()    # Canon iR2625/2630: Max 300 DPI
	LOW_MEMORY_SCALING = auto()    # Lexmark CX317dn: May scale 600→400 DPI
	
	# WSD-Specific Quirks
	WSD_IMAGES_TO_TRANSFER = auto()  # Ricoh: Use 100 instead of 0
	WSD_SWAP_WIDTH_HEIGHT = auto()   # Kyocera: Swap W/H if needed
	
	# Format/Encoding Quirks
	JPEG_ONLY = auto()             # Some older devices only support JPEG
	NO_PDF = auto()                # Device claims PDF but can't deliver
	
	# Connection Quirks
	SLOW_INIT = auto()             # Device needs extra time to initialize
	NO_HTTPS = auto()              # HTTPS not working despite being advertised


@dataclass
class DeviceQuirks:
	"""Device-specific quirks configuration."""
	flags: set[QuirkFlag] = field(default_factory=set)
	next_load_delay_ms: int = 0
	max_resolution: int | None = None
	host_header: str | None = None
	init_delay_ms: int = 0
	retry_count: int = 3
	retry_delay_ms: int = 1000
	
	def has(self, flag: QuirkFlag) -> bool:
		"""Check if this quirk is enabled."""
		return flag in self.flags
	
	def __repr__(self) -> str:
		flag_names = [f.name for f in self.flags]
		return f"DeviceQuirks(flags={flag_names})"


# Complete quirks database from sane-airscan and similar projects
QUIRKS_DATABASE: dict[str, DeviceQuirks] = {
	# ===================
	# HP Devices - localhost header quirk
	# Many HP devices require Host header to be "localhost"
	# ===================
	'HP LaserJet MFP M630': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP Color LaserJet FlowMFP M578': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP Color LaserJet MFP M181': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP LaserJet MFP M227': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP LaserJet MFP M426': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP LaserJet MFP M428': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP LaserJet MFP M429': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP LaserJet MFP M430': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP OfficeJet Pro 6970': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP OfficeJet Pro 8020': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP OfficeJet Pro 8025': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP OfficeJet Pro 9010': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP OfficeJet Pro 9020': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP ENVY 5540': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP ENVY 6000': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP DeskJet 3700': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP DeskJet 4100': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	'HP ScanJet Pro': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),
	
	# Generic HP pattern - catch-all for HP devices with Compact Server
	'HP': DeviceQuirks(
		flags={QuirkFlag.LOCALHOST_HEADER},
		host_header='localhost'
	),

	# ===================
	# EPSON Devices - port in host header
	# EPSON devices need port number in Host header
	# ===================
	'EPSON': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'Epson': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON WF-7710': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON WF-7720': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON WF-7840': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON ET-2720': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON ET-2750': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON ET-3760': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON ET-4750': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON L3150': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON L3250': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON L4150': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),
	'EPSON L4160': DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST}),

	# ===================
	# Brother Devices - load delay between pages
	# Brother devices need delay between LOAD requests for ADF
	# ===================
	'Brother': DeviceQuirks(
		flags={QuirkFlag.NEXT_LOAD_DELAY},
		next_load_delay_ms=1000
	),
	'Brother MFC': DeviceQuirks(
		flags={QuirkFlag.NEXT_LOAD_DELAY},
		next_load_delay_ms=1000
	),
	'Brother DCP': DeviceQuirks(
		flags={QuirkFlag.NEXT_LOAD_DELAY},
		next_load_delay_ms=1000
	),
	'Brother MFC-J4420DW': DeviceQuirks(
		flags={QuirkFlag.NEXT_LOAD_DELAY},
		next_load_delay_ms=1000
	),
	'Brother MFC-L2710DW': DeviceQuirks(
		flags={QuirkFlag.NEXT_LOAD_DELAY},
		next_load_delay_ms=1000
	),
	'Brother MFC-L2750DW': DeviceQuirks(
		flags={QuirkFlag.NEXT_LOAD_DELAY},
		next_load_delay_ms=1000
	),
	'Brother MFC-L8900CDW': DeviceQuirks(
		flags={QuirkFlag.NEXT_LOAD_DELAY},
		next_load_delay_ms=1000
	),
	'Brother ADS-2700W': DeviceQuirks(
		flags={QuirkFlag.NEXT_LOAD_DELAY},
		next_load_delay_ms=1000
	),
	'Brother ADS-3600W': DeviceQuirks(
		flags={QuirkFlag.NEXT_LOAD_DELAY},
		next_load_delay_ms=1000
	),

	# ===================
	# Canon Devices - ADF state check and resolution caps
	# Canon MF series needs ADF state validation
	# Canon iR series has resolution limitations
	# ===================
	'Canon MF410': DeviceQuirks(flags={QuirkFlag.CHECK_ADF_STATE}),
	'Canon MF260': DeviceQuirks(flags={QuirkFlag.CHECK_ADF_STATE}),
	'Canon MF440': DeviceQuirks(flags={QuirkFlag.CHECK_ADF_STATE}),
	'Canon MF640': DeviceQuirks(flags={QuirkFlag.CHECK_ADF_STATE}),
	'Canon MF740': DeviceQuirks(flags={QuirkFlag.CHECK_ADF_STATE}),
	'Canon imageCLASS MF': DeviceQuirks(flags={QuirkFlag.CHECK_ADF_STATE}),
	
	'Canon iR2625': DeviceQuirks(
		flags={QuirkFlag.CAP_RESOLUTION_300},
		max_resolution=300
	),
	'Canon iR2630': DeviceQuirks(
		flags={QuirkFlag.CAP_RESOLUTION_300},
		max_resolution=300
	),
	'Canon iR-ADV': DeviceQuirks(
		flags={QuirkFlag.CAP_RESOLUTION_300},
		max_resolution=300
	),
	'Canon imageRUNNER ADVANCE': DeviceQuirks(
		flags={QuirkFlag.CAP_RESOLUTION_300},
		max_resolution=300
	),

	# ===================
	# Xerox Devices - various protocol quirks
	# Xerox B205/B215 have multiple quirks
	# WorkCentre has ADF and retry quirks
	# ===================
	'Xerox B205': DeviceQuirks(
		flags={
			QuirkFlag.RETRY_ON_404,
			QuirkFlag.RETRY_ON_410,
			QuirkFlag.BROKEN_IPV6_LOCATION,
			QuirkFlag.SKIP_CLEANUP,
		},
		retry_count=5,
		retry_delay_ms=1000
	),
	'Xerox B215': DeviceQuirks(
		flags={
			QuirkFlag.RETRY_ON_404,
			QuirkFlag.RETRY_ON_410,
			QuirkFlag.BROKEN_IPV6_LOCATION,
			QuirkFlag.SKIP_CLEANUP,
		},
		retry_count=5,
		retry_delay_ms=1000
	),
	'Xerox WorkCentre 3345': DeviceQuirks(
		flags={QuirkFlag.CHECK_ADF_STATE, QuirkFlag.RETRY_ON_410},
		retry_count=5,
		retry_delay_ms=1000
	),
	'Xerox WorkCentre 6027': DeviceQuirks(flags=set()),
	'Xerox VersaLink': DeviceQuirks(flags=set()),
	'Xerox AltaLink': DeviceQuirks(flags=set()),

	# ===================
	# Lexmark Devices - memory constraints
	# Some Lexmark devices may downscale due to memory
	# ===================
	'Lexmark CX317': DeviceQuirks(
		flags={QuirkFlag.LOW_MEMORY_SCALING},
		max_resolution=400
	),
	'Lexmark CX417': DeviceQuirks(
		flags={QuirkFlag.LOW_MEMORY_SCALING},
		max_resolution=400
	),
	'Lexmark CX517': DeviceQuirks(
		flags={QuirkFlag.LOW_MEMORY_SCALING}
	),
	'Lexmark MC': DeviceQuirks(flags=set()),
	'Lexmark MX': DeviceQuirks(flags=set()),

	# ===================
	# Ricoh Devices - WSD quirks
	# Ricoh needs ImagesToTransfer=100 instead of 0
	# ===================
	'Ricoh Aficio MP 201': DeviceQuirks(
		flags={QuirkFlag.WSD_IMAGES_TO_TRANSFER}
	),
	'Ricoh MP C3003': DeviceQuirks(flags=set()),
	'Ricoh MP C4503': DeviceQuirks(flags=set()),
	'Ricoh IM C': DeviceQuirks(flags=set()),

	# ===================
	# Kyocera Devices - WSD width/height swap
	# Kyocera may need width/height swapped
	# ===================
	'Kyocera ECOSYS M2040': DeviceQuirks(
		flags={QuirkFlag.WSD_SWAP_WIDTH_HEIGHT}
	),
	'Kyocera ECOSYS M2540': DeviceQuirks(
		flags={QuirkFlag.WSD_SWAP_WIDTH_HEIGHT}
	),
	'Kyocera ECOSYS M5521': DeviceQuirks(flags=set()),
	'Kyocera TASKalfa': DeviceQuirks(flags=set()),

	# ===================
	# Samsung Devices - generally well-behaved
	# ===================
	'Samsung M337': DeviceQuirks(flags=set()),
	'Samsung M387': DeviceQuirks(flags=set()),
	'Samsung M407': DeviceQuirks(flags=set()),
	'Samsung MultiXpress': DeviceQuirks(flags=set()),

	# ===================
	# Konica Minolta - generally well-behaved
	# ===================
	'Konica Minolta bizhub': DeviceQuirks(flags=set()),
	'KONICA MINOLTA': DeviceQuirks(flags=set()),

	# ===================
	# Fujitsu - generally well-behaved
	# ===================
	'Fujitsu fi-': DeviceQuirks(flags=set()),
	'Fujitsu ScanSnap': DeviceQuirks(flags=set()),

	# ===================
	# Sharp - generally well-behaved
	# ===================
	'Sharp MX': DeviceQuirks(flags=set()),
	'Sharp BP': DeviceQuirks(flags=set()),

	# ===================
	# Toshiba - generally well-behaved
	# ===================
	'Toshiba e-STUDIO': DeviceQuirks(flags=set()),
}


def detect_quirks(
	model: str,
	manufacturer: str = '',
	server_header: str = ''
) -> DeviceQuirks:
	"""
	Detect device quirks from model name, manufacturer, or server header.
	
	Args:
		model: Device model name (e.g., "HP LaserJet MFP M181fw")
		manufacturer: Device manufacturer (e.g., "HP", "EPSON")
		server_header: HTTP Server header from device response
		
	Returns:
		DeviceQuirks configuration for this device
	"""
	# Check server header for HP Compact Server (indicates HP localhost quirk)
	if server_header:
		if 'HP_Compact_Server' in server_header:
			return DeviceQuirks(
				flags={QuirkFlag.LOCALHOST_HEADER},
				host_header='localhost'
			)
		if 'HP-ChaiSOE' in server_header:
			return DeviceQuirks(
				flags={QuirkFlag.LOCALHOST_HEADER},
				host_header='localhost'
			)
	
	# Check manufacturer first for generic brand quirks
	if manufacturer:
		manufacturer_upper = manufacturer.upper()
		if manufacturer_upper == 'EPSON':
			return DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST})
		if manufacturer_upper in ('HP', 'HEWLETT-PACKARD', 'HEWLETT PACKARD'):
			return DeviceQuirks(
				flags={QuirkFlag.LOCALHOST_HEADER},
				host_header='localhost'
			)
		if manufacturer_upper == 'BROTHER':
			return DeviceQuirks(
				flags={QuirkFlag.NEXT_LOAD_DELAY},
				next_load_delay_ms=1000
			)
	
	# Check model against database (case-insensitive substring match)
	model_lower = model.lower() if model else ''
	for pattern, quirks in QUIRKS_DATABASE.items():
		if pattern.lower() in model_lower:
			return quirks
	
	# Check for brand prefixes in model name
	if model_lower.startswith('hp ') or 'hewlett' in model_lower:
		return DeviceQuirks(
			flags={QuirkFlag.LOCALHOST_HEADER},
			host_header='localhost'
		)
	if model_lower.startswith('epson '):
		return DeviceQuirks(flags={QuirkFlag.PORT_IN_HOST})
	if model_lower.startswith('brother '):
		return DeviceQuirks(
			flags={QuirkFlag.NEXT_LOAD_DELAY},
			next_load_delay_ms=1000
		)
	
	# Default - no quirks
	return DeviceQuirks()


def get_effective_resolution(quirks: DeviceQuirks, requested_dpi: int) -> int:
	"""
	Get effective resolution considering device quirks.
	
	Some devices have resolution caps or may scale down due to memory.
	"""
	if quirks.max_resolution and requested_dpi > quirks.max_resolution:
		return quirks.max_resolution
	return requested_dpi


def should_retry_on_status(quirks: DeviceQuirks, status_code: int) -> bool:
	"""Check if we should retry based on HTTP status and device quirks."""
	if status_code == 404 and quirks.has(QuirkFlag.RETRY_ON_404):
		return True
	if status_code == 410 and quirks.has(QuirkFlag.RETRY_ON_410):
		return True
	return False
