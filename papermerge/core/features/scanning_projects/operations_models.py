# (c) Copyright Datacraft, 2026
"""ORM models for Scanning Operations (Safety, Custody)."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from papermerge.core.db.base import Base


class SafetyCheckModel(Base):
    """
    Tracks daily/shift-based PPE compliance and health checks for operators.
    Ensures workers are safety compliant before starting their shift.
    """
    __tablename__ = "safety_checks"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True
    )
    operator_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True
    )
    operator_name: Mapped[str] = mapped_column(String(255))
    
    # PPE Checklist
    has_gloves: Mapped[bool] = mapped_column(Boolean, default=False)
    has_mask: Mapped[bool] = mapped_column(Boolean, default=False)
    has_vest: Mapped[bool] = mapped_column(Boolean, default=False)
    has_shoes: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Health & Safety
    is_feeling_well: Mapped[bool] = mapped_column(Boolean, default=True)
    temperature_check: Mapped[float | None] = mapped_column(Float)  # Optional
    
    check_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notes: Mapped[str | None] = mapped_column(Text)
    
    # Verification
    verified_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL")
    )
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CustodyEventType(str, Enum):
    CHECK_OUT = "check_out"      # Warehouse -> Operator
    TRANSFER = "transfer"        # Operator -> Operator
    CHECK_IN = "check_in"        # Operator -> Warehouse
    SCAN_START = "scan_start"    # Operator starts scanning
    SCAN_END = "scan_end"        # Operator finishes scanning
    RETURN = "return"            # Returned to storage location


class ChainOfCustodyModel(Base):
    """
    Logs every physical movement and custody transfer of a ScanningBatch.
    Ensures full traceability of physical documents.
    """
    __tablename__ = "chain_of_custody"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True
    )
    batch_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scanning_batches.id", ondelete="CASCADE"),
        index=True
    )
    
    event_type: Mapped[CustodyEventType] = mapped_column(Enum(CustodyEventType))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # From (Previous Custodian/Location)
    from_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL")
    )
    from_location: Mapped[str | None] = mapped_column(String(255))
    
    # To (New Custodian/Location)
    to_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL")
    )
    to_location: Mapped[str | None] = mapped_column(String(255))
    
    # Verification
    signature_image_path: Mapped[str | None] = mapped_column(String(512))
    notes: Mapped[str | None] = mapped_column(Text)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
