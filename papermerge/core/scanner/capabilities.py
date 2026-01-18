# (c) Copyright Datacraft, 2026
"""Scanner capabilities models."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ColorMode(str, Enum):
	"""Color modes supported by scanners."""
	COLOR = 'color'
	GRAYSCALE = 'grayscale'
	MONOCHROME = 'monochrome'
	AUTO = 'auto'


class InputSource(str, Enum):
	"""Input sources for scanning."""
	PLATEN = 'platen'  # Flatbed glass
	ADF = 'adf'  # Automatic Document Feeder
	ADF_DUPLEX = 'adf_duplex'  # ADF with duplex
	CAMERA = 'camera'  # Document camera


class ImageFormat(str, Enum):
	"""Supported output formats."""
	JPEG = 'jpeg'
	PNG = 'png'
	TIFF = 'tiff'
	PDF = 'pdf'
	BMP = 'bmp'


@dataclass
class Resolution:
	"""Resolution specification."""
	min_dpi: int = 75
	max_dpi: int = 600
	default_dpi: int = 300
	discrete_values: list[int] | None = None  # If not continuous

	def is_valid(self, dpi: int) -> bool:
		if self.discrete_values:
			return dpi in self.discrete_values
		return self.min_dpi <= dpi <= self.max_dpi


@dataclass
class ScanArea:
	"""Physical scan area dimensions."""
	min_x: float = 0  # mm
	min_y: float = 0  # mm
	max_x: float = 215.9  # Letter width (8.5")
	max_y: float = 355.6  # Legal height (14")

	@property
	def width(self) -> float:
		return self.max_x - self.min_x

	@property
	def height(self) -> float:
		return self.max_y - self.min_y


@dataclass
class ADFCapabilities:
	"""ADF-specific capabilities."""
	present: bool = False
	duplex: bool = False
	capacity: int = 0  # Max sheets
	supported_sizes: list[str] = field(default_factory=list)  # A4, Letter, etc.


@dataclass
class ScannerCapabilities:
	"""Complete scanner capabilities."""
	# Basic info
	protocol_version: str = '2.1'
	uuid: str = ''

	# Supported sources
	platen: bool = True
	adf: ADFCapabilities = field(default_factory=ADFCapabilities)

	# Resolution
	resolution: Resolution = field(default_factory=Resolution)

	# Color modes
	color_modes: list[ColorMode] = field(
		default_factory=lambda: [ColorMode.COLOR, ColorMode.GRAYSCALE]
	)

	# Output formats
	formats: list[ImageFormat] = field(
		default_factory=lambda: [ImageFormat.JPEG, ImageFormat.PNG]
	)

	# Scan area
	platen_area: ScanArea = field(default_factory=ScanArea)
	adf_area: ScanArea | None = None

	# Features
	auto_crop: bool = False
	auto_deskew: bool = False
	blank_page_removal: bool = False
	brightness_control: bool = True
	contrast_control: bool = True

	# Performance
	warm_up_time_seconds: int = 0
	pages_per_minute_adf: float = 0

	# Raw capabilities data (protocol-specific)
	raw_capabilities: dict[str, Any] = field(default_factory=dict)

	def supports_input_source(self, source: InputSource) -> bool:
		"""Check if input source is supported."""
		if source == InputSource.PLATEN:
			return self.platen
		if source == InputSource.ADF:
			return self.adf.present
		if source == InputSource.ADF_DUPLEX:
			return self.adf.present and self.adf.duplex
		return False

	def supports_color_mode(self, mode: ColorMode) -> bool:
		"""Check if color mode is supported."""
		return mode in self.color_modes

	def supports_format(self, fmt: ImageFormat) -> bool:
		"""Check if output format is supported."""
		return fmt in self.formats

	def get_default_options(self) -> dict:
		"""Get default scan options based on capabilities."""
		return {
			'resolution': self.resolution.default_dpi,
			'color_mode': self.color_modes[0].value if self.color_modes else 'color',
			'input_source': 'platen' if self.platen else 'adf',
			'format': self.formats[0].value if self.formats else 'jpeg',
		}

	@classmethod
	def from_escl(cls, data: dict) -> "ScannerCapabilities":
		"""Parse capabilities from eSCL XML data."""
		caps = cls()
		caps.raw_capabilities = data

		# Parse platen
		caps.platen = 'Platen' in data.get('InputSources', [])

		# Parse ADF
		sources = data.get('InputSources', [])
		if 'Feeder' in sources or 'ADFFront' in sources:
			caps.adf = ADFCapabilities(
				present=True,
				duplex='ADFDuplex' in sources or 'ADFBack' in sources,
			)

		# Parse resolutions
		resolutions = data.get('Resolutions', [])
		if resolutions:
			caps.resolution = Resolution(
				min_dpi=min(resolutions),
				max_dpi=max(resolutions),
				default_dpi=300 if 300 in resolutions else resolutions[0],
				discrete_values=resolutions,
			)

		# Parse color modes
		modes = data.get('ColorModes', [])
		caps.color_modes = []
		mode_map = {
			'RGB24': ColorMode.COLOR,
			'Color': ColorMode.COLOR,
			'Grayscale8': ColorMode.GRAYSCALE,
			'Grayscale': ColorMode.GRAYSCALE,
			'BlackAndWhite1': ColorMode.MONOCHROME,
			'BlackAndWhite': ColorMode.MONOCHROME,
		}
		for mode in modes:
			if mode in mode_map:
				caps.color_modes.append(mode_map[mode])

		# Parse formats
		formats = data.get('DocumentFormats', [])
		caps.formats = []
		format_map = {
			'image/jpeg': ImageFormat.JPEG,
			'image/png': ImageFormat.PNG,
			'image/tiff': ImageFormat.TIFF,
			'application/pdf': ImageFormat.PDF,
		}
		for fmt in formats:
			if fmt in format_map:
				caps.formats.append(format_map[fmt])

		# Parse scan area
		if 'PlatenInputCaps' in data:
			platen = data['PlatenInputCaps']
			caps.platen_area = ScanArea(
				min_x=platen.get('MinWidth', 0) * 25.4 / 300,
				min_y=platen.get('MinHeight', 0) * 25.4 / 300,
				max_x=platen.get('MaxWidth', 2550) * 25.4 / 300,
				max_y=platen.get('MaxHeight', 4200) * 25.4 / 300,
			)

		return caps

	@classmethod
	def from_sane(cls, device_options: list) -> "ScannerCapabilities":
		"""Parse capabilities from SANE options."""
		caps = cls()
		caps.raw_capabilities = {'sane_options': device_options}

		# Common SANE option names
		for opt in device_options:
			name = opt.get('name', '')

			if name == 'resolution':
				constraint = opt.get('constraint')
				if isinstance(constraint, list):
					caps.resolution = Resolution(
						min_dpi=min(constraint),
						max_dpi=max(constraint),
						default_dpi=opt.get('value', 300),
						discrete_values=constraint,
					)
				elif isinstance(constraint, tuple) and len(constraint) == 3:
					# (min, max, step)
					caps.resolution = Resolution(
						min_dpi=constraint[0],
						max_dpi=constraint[1],
						default_dpi=opt.get('value', 300),
					)

			elif name == 'mode':
				constraint = opt.get('constraint', [])
				caps.color_modes = []
				mode_map = {
					'Color': ColorMode.COLOR,
					'Gray': ColorMode.GRAYSCALE,
					'Lineart': ColorMode.MONOCHROME,
				}
				for mode in constraint:
					if mode in mode_map:
						caps.color_modes.append(mode_map[mode])

			elif name == 'source':
				constraint = opt.get('constraint', [])
				caps.platen = 'Flatbed' in constraint or 'platen' in str(constraint).lower()
				if any('ADF' in s or 'Feeder' in s for s in constraint):
					caps.adf = ADFCapabilities(
						present=True,
						duplex=any('Duplex' in s for s in constraint),
					)

			elif name == 'br-x':
				caps.platen_area.max_x = opt.get('constraint', (0, 215.9))[1]

			elif name == 'br-y':
				caps.platen_area.max_y = opt.get('constraint', (0, 355.6))[1]

		# Default formats for SANE (depends on backend)
		caps.formats = [ImageFormat.PNG, ImageFormat.TIFF, ImageFormat.JPEG]

		return caps
