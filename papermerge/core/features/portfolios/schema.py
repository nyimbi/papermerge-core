# (c) Copyright Datacraft, 2026
"""Portfolio Pydantic schemas."""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class PortfolioCreate(BaseModel):
	"""Schema for creating a portfolio."""
	name: str
	description: str | None = None
	portfolio_type: str = "general"
	metadata: dict | None = None


class PortfolioUpdate(BaseModel):
	"""Schema for updating a portfolio."""
	name: str | None = None
	description: str | None = None
	metadata: dict | None = None


class PortfolioInfo(BaseModel):
	"""Basic portfolio information."""
	id: UUID
	name: str
	description: str | None = None
	portfolio_type: str
	created_at: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class PortfolioDetail(BaseModel):
	"""Detailed portfolio information."""
	id: UUID
	name: str
	description: str | None = None
	portfolio_type: str
	metadata: dict | None = None
	case_count: int = 0
	created_at: datetime | None = None


class PortfolioListResponse(BaseModel):
	"""Paginated portfolio list."""
	items: list[PortfolioInfo]
	total: int
	page: int
	page_size: int


class GrantPortfolioAccessRequest(BaseModel):
	"""Request to grant portfolio access."""
	subject_type: str  # user, group, role
	subject_id: UUID
	allow_view: bool = True
	allow_download: bool = False
	allow_print: bool = False
	allow_edit: bool = False
	allow_share: bool = False
	inherit_to_cases: bool = True
	valid_from: datetime | None = None
	valid_until: datetime | None = None


class PortfolioAccessInfo(BaseModel):
	"""Portfolio access information."""
	id: UUID
	portfolio_id: UUID
	subject_type: str
	subject_id: UUID
	allow_view: bool
	allow_download: bool
	allow_print: bool
	allow_edit: bool
	allow_share: bool
	inherit_to_cases: bool
	valid_from: datetime | None = None
	valid_until: datetime | None = None

	model_config = ConfigDict(from_attributes=True)


class PortfolioCasesResponse(BaseModel):
	"""Response with portfolio cases."""
	items: list  # CaseInfo from cases feature
	total: int
	page: int
	page_size: int
