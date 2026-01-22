# (c) Copyright Datacraft, 2026
"""Scanner management API endpoints."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.db.engine import get_session
from papermerge.core.auth import get_current_user
from papermerge.core.db.models import User

from .views import (
	ScannerCreate, ScannerUpdate, ScannerResponse, ScannerStatusResponse,
	DiscoveredScannerResponse, ScannerCapabilitiesResponse,
	ScanJobCreate, ScanJobResponse, ScanJobResultResponse,
	ScanProfileCreate, ScanProfileUpdate, ScanProfileResponse,
	GlobalScannerSettingsUpdate, GlobalScannerSettingsResponse,
	ScannerDashboard, ScannerUsageStats, ScannerApiKeyResponse,
)
from . import service

router = APIRouter(prefix="/scanners", tags=["scanners"])


# === Discovery ===

@router.get("/discover", response_model=list[DiscoveredScannerResponse])
async def discover_scanners(
	user: Annotated[User, Depends(get_current_user)],
	timeout: float = Query(default=8.0, ge=1.0, le=30.0),
	force_refresh: bool = Query(default=False),
) -> list[DiscoveredScannerResponse]:
	"""Discover available scanners on the network and locally."""
	return await service.discover_scanners(timeout=timeout, force_refresh=force_refresh)


# === Scanner CRUD ===

@router.get("", response_model=list[ScannerResponse])
async def list_scanners(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
	include_inactive: bool = Query(default=False),
) -> list[ScannerResponse]:
	"""List all registered scanners for the tenant."""
	return await service.get_scanners(
		session=session,
		tenant_id=user.tenant_id,
		include_inactive=include_inactive,
	)


@router.post("", response_model=ScannerResponse, status_code=201)
async def register_scanner(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
	data: ScannerCreate,
) -> ScannerResponse:
	"""Register a new scanner."""
	return await service.create_scanner(
		session=session,
		tenant_id=user.tenant_id,
		data=data,
	)


@router.get("/{scanner_id}", response_model=ScannerResponse)
async def get_scanner(
	scanner_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScannerResponse:
	"""Get scanner details."""
	scanner = await service.get_scanner_by_id(
		session=session,
		scanner_id=scanner_id,
		tenant_id=user.tenant_id,
	)
	if not scanner:
		raise HTTPException(status_code=404, detail="Scanner not found")
	return scanner


@router.patch("/{scanner_id}", response_model=ScannerResponse)
async def update_scanner(
	scanner_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
	data: ScannerUpdate,
) -> ScannerResponse:
	"""Update scanner configuration."""
	scanner = await service.update_scanner(
		session=session,
		scanner_id=scanner_id,
		tenant_id=user.tenant_id,
		data=data,
	)
	if not scanner:
		raise HTTPException(status_code=404, detail="Scanner not found")
	return scanner


@router.delete("/{scanner_id}", status_code=204)
async def delete_scanner(
	scanner_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
	"""Remove a scanner registration."""
	deleted = await service.delete_scanner(
		session=session,
		scanner_id=scanner_id,
		tenant_id=user.tenant_id,
	)
	if not deleted:
		raise HTTPException(status_code=404, detail="Scanner not found")


@router.post("/{scanner_id}/api-key", response_model=ScannerApiKeyResponse)
async def generate_scanner_api_key(
	scanner_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScannerApiKeyResponse:
	"""Generate or rotate the API key for a scanner."""
	result = await service.generate_scanner_api_key(
		session=session,
		scanner_id=scanner_id,
		tenant_id=user.tenant_id,
	)
	if not result:
		raise HTTPException(status_code=404, detail="Scanner not found")
	return result


# === Scanner Status & Capabilities ===

@router.get("/{scanner_id}/status", response_model=ScannerStatusResponse)
async def get_scanner_status(
	scanner_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScannerStatusResponse:
	"""Get real-time scanner status."""
	status = await service.get_scanner_status(
		session=session,
		scanner_id=scanner_id,
		tenant_id=user.tenant_id,
	)
	if not status:
		raise HTTPException(status_code=404, detail="Scanner not found")
	return status


@router.get("/{scanner_id}/capabilities", response_model=ScannerCapabilitiesResponse)
async def get_scanner_capabilities(
	scanner_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScannerCapabilitiesResponse:
	"""Get scanner capabilities."""
	capabilities = await service.get_scanner_capabilities(
		session=session,
		scanner_id=scanner_id,
		tenant_id=user.tenant_id,
	)
	if not capabilities:
		raise HTTPException(status_code=404, detail="Scanner not found or capabilities unavailable")
	return capabilities


@router.post("/{scanner_id}/refresh-capabilities", response_model=ScannerCapabilitiesResponse)
async def refresh_scanner_capabilities(
	scanner_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScannerCapabilitiesResponse:
	"""Refresh scanner capabilities from device."""
	capabilities = await service.refresh_scanner_capabilities(
		session=session,
		scanner_id=scanner_id,
		tenant_id=user.tenant_id,
	)
	if not capabilities:
		raise HTTPException(status_code=404, detail="Scanner not found or unreachable")
	return capabilities


# === Scan Jobs ===

@router.post("/jobs", response_model=ScanJobResponse, status_code=201)
async def create_scan_job(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
	background_tasks: BackgroundTasks,
	data: ScanJobCreate,
) -> ScanJobResponse:
	"""Create and start a new scan job."""
	job = await service.create_scan_job(
		session=session,
		tenant_id=user.tenant_id,
		user_id=user.id,
		data=data,
	)
	# Execute scan in background
	background_tasks.add_task(
		service.execute_scan_job,
		session=session,
		job_id=job.id,
		tenant_id=user.tenant_id,
	)
	return job


@router.get("/jobs", response_model=list[ScanJobResponse])
async def list_scan_jobs(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
	scanner_id: str | None = Query(default=None),
	status: str | None = Query(default=None),
	limit: int = Query(default=50, ge=1, le=200),
) -> list[ScanJobResponse]:
	"""List scan jobs."""
	return await service.get_scan_jobs(
		session=session,
		tenant_id=user.tenant_id,
		user_id=user.id,
		scanner_id=scanner_id,
		status=status,
		limit=limit,
	)


@router.get("/jobs/{job_id}", response_model=ScanJobResponse)
async def get_scan_job(
	job_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScanJobResponse:
	"""Get scan job details."""
	job = await service.get_scan_job_by_id(
		session=session,
		job_id=job_id,
		tenant_id=user.tenant_id,
	)
	if not job:
		raise HTTPException(status_code=404, detail="Scan job not found")
	return job


@router.post("/jobs/{job_id}/cancel", response_model=ScanJobResponse)
async def cancel_scan_job(
	job_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScanJobResponse:
	"""Cancel a running scan job."""
	job = await service.cancel_scan_job(
		session=session,
		job_id=job_id,
		tenant_id=user.tenant_id,
	)
	if not job:
		raise HTTPException(status_code=404, detail="Scan job not found")
	return job


@router.get("/jobs/{job_id}/result", response_model=ScanJobResultResponse)
async def get_scan_job_result(
	job_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScanJobResultResponse:
	"""Get scan job result with document IDs."""
	result = await service.get_scan_job_result(
		session=session,
		job_id=job_id,
		tenant_id=user.tenant_id,
	)
	if not result:
		raise HTTPException(status_code=404, detail="Scan job not found or not completed")
	return result


# === Scan Profiles ===

@router.get("/profiles", response_model=list[ScanProfileResponse])
async def list_scan_profiles(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ScanProfileResponse]:
	"""List scan profiles."""
	return await service.get_scan_profiles(
		session=session,
		tenant_id=user.tenant_id,
	)


@router.post("/profiles", response_model=ScanProfileResponse, status_code=201)
async def create_scan_profile(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
	data: ScanProfileCreate,
) -> ScanProfileResponse:
	"""Create a scan profile."""
	return await service.create_scan_profile(
		session=session,
		tenant_id=user.tenant_id,
		created_by_id=user.id,
		data=data,
	)


@router.get("/profiles/{profile_id}", response_model=ScanProfileResponse)
async def get_scan_profile(
	profile_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScanProfileResponse:
	"""Get scan profile details."""
	profile = await service.get_scan_profile_by_id(
		session=session,
		profile_id=profile_id,
		tenant_id=user.tenant_id,
	)
	if not profile:
		raise HTTPException(status_code=404, detail="Scan profile not found")
	return profile


@router.patch("/profiles/{profile_id}", response_model=ScanProfileResponse)
async def update_scan_profile(
	profile_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
	data: ScanProfileUpdate,
) -> ScanProfileResponse:
	"""Update scan profile."""
	profile = await service.update_scan_profile(
		session=session,
		profile_id=profile_id,
		tenant_id=user.tenant_id,
		data=data,
	)
	if not profile:
		raise HTTPException(status_code=404, detail="Scan profile not found")
	return profile


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_scan_profile(
	profile_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
	"""Delete scan profile."""
	deleted = await service.delete_scan_profile(
		session=session,
		profile_id=profile_id,
		tenant_id=user.tenant_id,
	)
	if not deleted:
		raise HTTPException(status_code=404, detail="Scan profile not found")


# === Global Settings ===

@router.get("/settings", response_model=GlobalScannerSettingsResponse)
async def get_scanner_settings(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> GlobalScannerSettingsResponse:
	"""Get global scanner settings."""
	return await service.get_scanner_settings(
		session=session,
		tenant_id=user.tenant_id,
	)


@router.patch("/settings", response_model=GlobalScannerSettingsResponse)
async def update_scanner_settings(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
	data: GlobalScannerSettingsUpdate,
) -> GlobalScannerSettingsResponse:
	"""Update global scanner settings."""
	return await service.update_scanner_settings(
		session=session,
		tenant_id=user.tenant_id,
		data=data,
	)


# === Dashboard & Analytics ===

@router.get("/dashboard", response_model=ScannerDashboard)
async def get_scanner_dashboard(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
) -> ScannerDashboard:
	"""Get scanner dashboard overview."""
	return await service.get_scanner_dashboard(
		session=session,
		tenant_id=user.tenant_id,
	)


@router.get("/stats", response_model=list[ScannerUsageStats])
async def get_scanner_usage_stats(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_session)],
	days: int = Query(default=30, ge=1, le=365),
) -> list[ScannerUsageStats]:
	"""Get scanner usage statistics."""
	return await service.get_scanner_usage_stats(
		session=session,
		tenant_id=user.tenant_id,
		days=days,
	)
