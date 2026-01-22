# (c) Copyright Datacraft, 2026
"""Scanner management ORM models."""
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid_extensions import uuid7str

from papermerge.core.db.base import Base

if TYPE_CHECKING:
	from papermerge.core.db.models import Tenant, User


class ScannerModel(Base):
	"""Registered scanner device."""
	__tablename__ = 'scanners'

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	protocol: Mapped[str] = mapped_column(String(20), nullable=False)  # escl, sane, twain, wia
	connection_uri: Mapped[str] = mapped_column(String(500), nullable=False)

	# Device info
	manufacturer: Mapped[str | None] = mapped_column(String(255))
	model: Mapped[str | None] = mapped_column(String(255))
	serial_number: Mapped[str | None] = mapped_column(String(100))
	firmware_version: Mapped[str | None] = mapped_column(String(50))

	# Status
	status: Mapped[str] = mapped_column(String(20), default='offline')  # online, offline, busy, error, maintenance
	last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
	last_error: Mapped[str | None] = mapped_column(Text)

	# Configuration
	location_id: Mapped[str | None] = mapped_column(String(36))  # Link to scanning_locations
	is_default: Mapped[bool] = mapped_column(Boolean, default=False)
	is_active: Mapped[bool] = mapped_column(Boolean, default=True)
	api_key_hash: Mapped[str | None] = mapped_column(String(128), index=True)
	notes: Mapped[str | None] = mapped_column(Text)

	# Capabilities cached as JSON
	capabilities: Mapped[dict | None] = mapped_column(JSON)

	# Statistics
	total_pages_scanned: Mapped[int] = mapped_column(Integer, default=0)
	total_jobs: Mapped[int] = mapped_column(Integer, default=0)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ScanJobModel(Base):
	"""Scan job record."""
	__tablename__ = 'scan_jobs'

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
	scanner_id: Mapped[str] = mapped_column(String(36), ForeignKey('scanners.id', ondelete='SET NULL'), index=True)
	user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

	# Status
	status: Mapped[str] = mapped_column(String(20), default='pending')  # pending, scanning, processing, completed, cancelled, failed
	error_message: Mapped[str | None] = mapped_column(Text)

	# Options (stored as JSON)
	options: Mapped[dict] = mapped_column(JSON, default=dict)

	# Results
	pages_scanned: Mapped[int] = mapped_column(Integer, default=0)
	scan_time_ms: Mapped[float | None] = mapped_column(Float)
	document_ids: Mapped[list | None] = mapped_column(JSON)  # Created document IDs

	# Associations
	project_id: Mapped[str | None] = mapped_column(String(36))
	batch_id: Mapped[str | None] = mapped_column(String(36))
	physical_manifest_id: Mapped[str | None] = mapped_column(String(36))
	destination_folder_id: Mapped[str | None] = mapped_column(String(36))

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
	started_at: Mapped[datetime | None] = mapped_column(DateTime)
	completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ScanProfileModel(Base):
	"""Saved scan profile/preset."""
	__tablename__ = 'scan_profiles'

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
	created_by_id: Mapped[str] = mapped_column(String(36), nullable=False)

	name: Mapped[str] = mapped_column(String(100), nullable=False)
	description: Mapped[str | None] = mapped_column(String(500))
	is_default: Mapped[bool] = mapped_column(Boolean, default=False)

	# Options stored as JSON
	options: Mapped[dict] = mapped_column(JSON, default=dict)

	# Timestamps
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ScannerSettingsModel(Base):
	"""Global scanner settings per tenant."""
	__tablename__ = 'scanner_settings'

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7str)
	tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, unique=True)

	auto_discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
	discovery_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
	default_profile_id: Mapped[str | None] = mapped_column(String(36))
	auto_process_scans: Mapped[bool] = mapped_column(Boolean, default=True)
	default_destination_folder_id: Mapped[str | None] = mapped_column(String(36))

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
