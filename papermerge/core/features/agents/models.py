"""SQLAlchemy model for the scan agent registry."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


class AgentModel(Base):
	__tablename__ = "scan_agents"

	id: Mapped[str] = mapped_column(String(36), primary_key=True)
	tenant_id: Mapped[str] = mapped_column(
		String(36), nullable=False, index=True
	)
	name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
	hostname: Mapped[str] = mapped_column(String(255), nullable=False)
	platform: Mapped[str] = mapped_column(String(32), nullable=False)
	version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
	port: Mapped[int] = mapped_column(Integer, nullable=False, default=7780)
	ip_address: Mapped[str | None] = mapped_column(String(64))
	pushed_config: Mapped[dict | None] = mapped_column(JSONB)
	last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), server_default=func.now(), nullable=False
	)
	updated_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True), server_default=func.now(),
		onupdate=func.now(), nullable=False
	)
