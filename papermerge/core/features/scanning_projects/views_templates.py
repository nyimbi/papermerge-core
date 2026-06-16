# (c) Copyright Datacraft, 2026
"""Pydantic schemas for Batch Templates."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BatchTemplateBase(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True, from_attributes=True)

	name: str = Field(..., min_length=1, max_length=255)
	description: str | None = None
	dpi: int = Field(default=300, ge=72, le=1200)
	color_mode: str = Field(default="color")       # color | grayscale | black_white
	paper_size: str = Field(default="A4")           # A4 | A3 | Letter | Legal | auto
	quality_threshold: float = Field(default=60.0, ge=0.0, le=100.0)
	barcode_enabled: bool = False
	auto_deskew: bool = True
	auto_enhance: bool = False
	expected_pages_per_document: int | None = Field(default=None, ge=1)
	notes_template: str | None = None


class BatchTemplateCreate(BatchTemplateBase):
	pass


class BatchTemplateUpdate(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)

	name: str | None = Field(default=None, min_length=1, max_length=255)
	description: str | None = None
	dpi: int | None = Field(default=None, ge=72, le=1200)
	color_mode: str | None = None
	paper_size: str | None = None
	quality_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
	barcode_enabled: bool | None = None
	auto_deskew: bool | None = None
	auto_enhance: bool | None = None
	expected_pages_per_document: int | None = None
	notes_template: str | None = None


class BatchTemplate(BatchTemplateBase):
	id: str
	tenant_id: str
	created_by_id: str
	created_at: datetime
	updated_at: datetime
	usage_count: int = 0
