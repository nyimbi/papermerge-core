# (c) Copyright Datacraft, 2026
"""ORM models for physical manifest and inventory tracking."""
import uuid
from datetime import datetime
from uuid import UUID
from enum import Enum

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Boolean, Enum as SQLEnum, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from papermerge.core.db.base import Base


class ContainerType(str, Enum):
	"""Types of physical containers."""
	BOX = "box"
	FOLDER = "folder"
	CRATE = "crate"
	SHELF = "shelf"
	CABINET = "cabinet"
	PALLET = "pallet"
	ROOM = "room"
	BUILDING = "building"


class InventoryStatus(str, Enum):
	"""Status of inventory items."""
	IN_STORAGE = "in_storage"
	CHECKED_OUT = "checked_out"
	IN_TRANSIT = "in_transit"
	MISSING = "missing"
	DESTROYED = "destroyed"
	TRANSFERRED = "transferred"
	PENDING_REVIEW = "pending_review"


class WarehouseLocation(Base):
	"""
	Physical warehouse/storage location hierarchy.
	Supports multi-level locations like Building > Room > Shelf > Slot.
	"""
	__tablename__ = "warehouse_locations"

	id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		primary_key=True,
		default=uuid.uuid4
	)
	code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
	name: Mapped[str] = mapped_column(String(200), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)

	# Hierarchical structure
	parent_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("warehouse_locations.id", ondelete="SET NULL"),
		index=True
	)
	path: Mapped[str] = mapped_column(String(1000), index=True)  # Materialized path: "A/B/C"
	level: Mapped[int] = mapped_column(Integer, default=0)

	# Location metadata
	capacity: Mapped[int | None] = mapped_column(Integer)  # Max containers
	current_count: Mapped[int] = mapped_column(Integer, default=0)
	climate_controlled: Mapped[bool] = mapped_column(Boolean, default=False)
	fire_suppression: Mapped[bool] = mapped_column(Boolean, default=False)
	access_restricted: Mapped[bool] = mapped_column(Boolean, default=False)

	# Physical coordinates for larger warehouses
	aisle: Mapped[str | None] = mapped_column(String(20))
	bay: Mapped[str | None] = mapped_column(String(20))
	shelf_number: Mapped[str | None] = mapped_column(String(20))
	position: Mapped[str | None] = mapped_column(String(20))

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

	tenant_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		index=True,
		nullable=False
	)


class PhysicalContainer(Base):
	"""
	Physical container (box, folder, crate) that holds documents.
	Trackable via barcode/QR code.
	"""
	__tablename__ = "physical_containers"

	id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		primary_key=True,
		default=uuid.uuid4
	)
	barcode: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
	container_type: Mapped[str] = mapped_column(
		SQLEnum(ContainerType, name="container_type_enum"),
		default=ContainerType.BOX
	)
	label: Mapped[str | None] = mapped_column(String(200))
	description: Mapped[str | None] = mapped_column(Text)

	# Current location
	location_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("warehouse_locations.id", ondelete="SET NULL"),
		index=True
	)

	# Container hierarchy (boxes can contain folders)
	parent_container_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("physical_containers.id", ondelete="SET NULL"),
		index=True
	)

	# Status tracking
	status: Mapped[str] = mapped_column(
		SQLEnum(InventoryStatus, name="inventory_status_enum"),
		default=InventoryStatus.IN_STORAGE
	)

	# Physical attributes
	item_count: Mapped[int] = mapped_column(Integer, default=0)
	weight_kg: Mapped[float | None] = mapped_column(Integer)  # Weight in kg * 100 (avoid float issues)
	dimensions: Mapped[dict | None] = mapped_column(JSON)  # {"width": 30, "height": 25, "depth": 40}

	# Retention
	retention_date: Mapped[datetime | None] = mapped_column(DateTime)
	destruction_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
	legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)

	# Chain of custody
	current_custodian_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="SET NULL")
	)
	last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
	last_verified_by_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="SET NULL")
	)

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
	updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

	tenant_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		index=True,
		nullable=False
	)

	# Link to scanning project if applicable
	scanning_project_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("scanning_projects.id", ondelete="SET NULL"),
		index=True
	)


class ContainerDocument(Base):
	"""
	Association between physical containers and digital documents.
	Tracks which document is in which container.
	"""
	__tablename__ = "container_documents"

	id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		primary_key=True,
		default=uuid.uuid4
	)
	container_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("physical_containers.id", ondelete="CASCADE"),
		index=True,
		nullable=False
	)
	document_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("documents.id", ondelete="CASCADE"),
		index=True,
		nullable=False
	)

	# Position within container
	sequence_number: Mapped[int | None] = mapped_column(Integer)

	# Physical document attributes
	page_count: Mapped[int | None] = mapped_column(Integer)
	has_physical: Mapped[bool] = mapped_column(Boolean, default=True)  # False if destroyed after scan

	# Status tracking
	verified: Mapped[bool] = mapped_column(Boolean, default=False)
	verified_at: Mapped[datetime | None] = mapped_column(DateTime)

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	tenant_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		index=True,
		nullable=False
	)


class CustodyEvent(Base):
	"""
	Chain of custody tracking for physical containers.
	Records every transfer, checkout, return.
	"""
	__tablename__ = "custody_events"

	id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		primary_key=True,
		default=uuid.uuid4
	)
	container_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("physical_containers.id", ondelete="CASCADE"),
		index=True,
		nullable=False
	)

	event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # checkout, return, transfer, verify, etc.

	# Who
	from_user_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="SET NULL")
	)
	to_user_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="SET NULL")
	)
	performed_by_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="SET NULL"),
		nullable=False
	)

	# Where
	from_location_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("warehouse_locations.id", ondelete="SET NULL")
	)
	to_location_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("warehouse_locations.id", ondelete="SET NULL")
	)

	# Details
	reason: Mapped[str | None] = mapped_column(Text)
	notes: Mapped[str | None] = mapped_column(Text)

	# Verification
	signature_captured: Mapped[bool] = mapped_column(Boolean, default=False)
	witness_name: Mapped[str | None] = mapped_column(String(200))

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	tenant_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		index=True,
		nullable=False
	)


class InventoryScan(Base):
	"""
	Records of barcode/QR scans for audit trail.
	Every scan is logged regardless of result.
	"""
	__tablename__ = "inventory_scans"

	id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		primary_key=True,
		default=uuid.uuid4
	)

	# What was scanned
	scanned_code: Mapped[str] = mapped_column(String(500), nullable=False)
	code_type: Mapped[str] = mapped_column(String(20))  # qr, datamatrix, code128, code39, etc.

	# Result
	success: Mapped[bool] = mapped_column(Boolean, default=True)
	resolved_container_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("physical_containers.id", ondelete="SET NULL")
	)
	resolved_document_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("documents.id", ondelete="SET NULL")
	)
	resolved_location_id: Mapped[UUID | None] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("warehouse_locations.id", ondelete="SET NULL")
	)
	error_message: Mapped[str | None] = mapped_column(Text)

	# Context
	scan_purpose: Mapped[str | None] = mapped_column(String(50))  # lookup, checkin, checkout, verify, move
	scanner_device_id: Mapped[str | None] = mapped_column(String(100))
	scanned_by_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("users.id", ondelete="SET NULL"),
		nullable=False
	)

	# GPS if mobile scanner
	latitude: Mapped[float | None] = mapped_column(Integer)  # lat * 1000000
	longitude: Mapped[float | None] = mapped_column(Integer)  # lng * 1000000

	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	tenant_id: Mapped[UUID] = mapped_column(
		PG_UUID(as_uuid=True),
		ForeignKey("tenants.id", ondelete="CASCADE"),
		index=True,
		nullable=False
	)


class PhysicalManifest(Base):
    """
    Represents a physical unit (box, folder, crate) that contains documents.
    Used for generating barcode sheets and tracking chain of custody.
    """
    __tablename__ = "physical_manifests"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    barcode: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    location_path: Mapped[str | None] = mapped_column(String(512))
    # e.g., "Warehouse A/Shelf 4/Box 12"
    
    responsible_person: Mapped[str | None] = mapped_column(String(100))
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
    
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    def __repr__(self):
        return f"PhysicalManifest(id={self.id}, barcode={self.barcode})"
