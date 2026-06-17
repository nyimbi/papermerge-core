# (c) Copyright Datacraft, 2026
"""ORM model for external connector configurations."""
from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from papermerge.core.db.base import Base


class ConnectorConfig(Base):
	__tablename__ = "connector_configs"

	id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
	name: Mapped[str] = mapped_column(String(255), nullable=False)
	# "google_drive" | "dropbox" | "onedrive" | "local_folder"
	connector_type: Mapped[str] = mapped_column(String(64), nullable=False)
	# JSON blob: auth tokens, folder IDs, etc. (encryption TODO)
	config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
	# Remote folder to watch (connector-side ID and human name)
	watch_folder_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
	watch_folder_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
	# Target papermerge folder (node id)
	destination_folder_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
	last_sync_at: Mapped[datetime | None] = mapped_column(
		DateTime(timezone=True), nullable=True
	)
	last_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
	is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
	sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
	tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
	created_by_id: Mapped[str] = mapped_column(String(64), nullable=False)
	created_at: Mapped[datetime] = mapped_column(
		DateTime(timezone=True),
		nullable=False,
		default=datetime.utcnow,
		server_default="now()",
	)
