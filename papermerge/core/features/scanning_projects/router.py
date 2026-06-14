# (c) Copyright Datacraft, 2026
"""FastAPI router for Scanning Projects feature."""
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from papermerge.core.auth import get_current_user
from papermerge.core.db.engine import get_db
from papermerge.core.features.users.schema import User

from . import service
from .ai_advisor import get_project_advisor
from .models import ScanningProjectModel
from .views import (
	QualityConfig,
	ScanningProject,
	ScanningProjectCreate,
	ScanningProjectUpdate,
	ScanningBatch,
	ScanningBatchCreate,
	ScanningBatchUpdate,
	ScanningBatchDocument,
	ScanningBatchDocumentCreate,
	ScanningMilestone,
	ScanningMilestoneCreate,
	ScanningMilestoneUpdate,
	QualityControlSample,
	QualityControlSampleCreate,
	QualityControlSampleUpdate,
	ScanningResource,
	ScanningResourceCreate,
	ScanningResourceUpdate,
	ScanningProjectMetrics,
	# New models
	ProjectPhase,
	ProjectPhaseCreate,
	ProjectPhaseUpdate,
	ScanningSession,
	ScanningSessionCreate,
	ScanningSessionEnd,
	ProgressSnapshot,
	DailyProjectMetrics,
	OperatorDailyMetrics,
	ProjectIssue,
	ProjectIssueCreate,
	ProjectIssueUpdate,
	AIAdvisorResponse,
	# Enterprise-scale models
	SubProject,
	SubProjectCreate,
	SubProjectUpdate,
	ScanningLocation,
	ScanningLocationCreate,
	ScanningLocationUpdate,
	Shift,
	ShiftCreate,
	ShiftUpdate,
	ShiftAssignment,
	ShiftAssignmentCreate,
	ShiftAssignmentBulkCreate,
	ProjectCost,
	ProjectCostCreate,
	ProjectBudget,
	ProjectBudgetCreate,
	ProjectBudgetUpdate,
	CostSummary,
	CostType,
	SLA,
	SLACreate,
	SLAUpdate,
	SLAAlert,
	EquipmentMaintenance,
	EquipmentMaintenanceCreate,
	EquipmentMaintenanceUpdate,
	MaintenanceStatus,
	OperatorCertification,
	OperatorCertificationCreate,
	OperatorCertificationUpdate,
	CapacityPlan,
	CapacityPlanCreate,
	DocumentTypeDistribution,
	DocumentTypeDistributionCreate,
	DocumentTypeDistributionUpdate,
	BatchPriority,
	BatchPriorityCreate,
	BatchPriorityUpdate,
	ProjectContract,
	ProjectContractCreate,
	ProjectContractUpdate,
	WorkloadForecast,
	ProjectCheckpoint,
	ProjectCheckpointCreate,
	ProjectCheckpointUpdate,
	BulkBatchImport,
	BulkBatchUpdate,
	BulkOperationResult,
	ProjectDashboard,
	BurndownChart,
	VelocityChart,
	MultiLocationDashboard,
)

router = APIRouter(prefix="/scanning-projects", tags=["scanning-projects"])


# =====================================================
# Projects Endpoints
# =====================================================


@router.get("", response_model=list[ScanningProject])
async def list_projects(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanningProject]:
	"""List all scanning projects for the current tenant."""
	projects = await service.get_scanning_projects(session, user.tenant_id)
	return list(projects)


@router.get("/{project_id}", response_model=ScanningProject)
async def get_project(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningProject:
	"""Get a scanning project by ID."""
	project = await service.get_scanning_project(session, project_id, user.tenant_id)
	if not project:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
	return project


@router.post("", response_model=ScanningProject, status_code=status.HTTP_201_CREATED)
async def create_project(
	data: ScanningProjectCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningProject:
	"""Create a new scanning project."""
	return await service.create_scanning_project(session, str(user.tenant_id), str(user.id), data)


@router.patch("/{project_id}", response_model=ScanningProject)
async def update_project(
	project_id: str,
	data: ScanningProjectUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningProject:
	"""Update a scanning project."""
	project = await service.update_scanning_project(session, project_id, user.tenant_id, data)
	if not project:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
	return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a scanning project."""
	deleted = await service.delete_scanning_project(session, project_id, user.tenant_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.get("/{project_id}/metrics", response_model=ScanningProjectMetrics)
async def get_project_metrics(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningProjectMetrics:
	"""Get metrics for a scanning project."""
	return await service.get_project_metrics(session, project_id)


# =====================================================
# Batches Endpoints
# =====================================================


@router.get("/{project_id}/batches", response_model=list[ScanningBatch])
async def list_batches(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanningBatch]:
	"""List all batches for a project."""
	batches = await service.get_project_batches(session, project_id, user.tenant_id)
	return list(batches)


@router.post(
	"/{project_id}/batches",
	response_model=ScanningBatch,
	status_code=status.HTTP_201_CREATED,
)
async def create_batch(
	project_id: str,
	data: ScanningBatchCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Create a new batch for a project."""
	return await service.create_batch(session, project_id, data)


@router.get("/{project_id}/batches/{batch_id}", response_model=ScanningBatch)
async def get_batch(
	project_id: str,
	batch_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Get a single batch by ID."""
	batch = await service.get_batch(session, batch_id)
	if not batch:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
	return batch


@router.patch("/{project_id}/batches/{batch_id}", response_model=ScanningBatch)
async def update_batch(
	project_id: str,
	batch_id: str,
	data: ScanningBatchUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Update a batch."""
	batch = await service.update_batch(session, batch_id, data)
	if not batch:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
	return batch


@router.post("/{project_id}/batches/{batch_id}/start-scan", response_model=ScanningBatch)
async def start_batch_scan(
	project_id: str,
	batch_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Start scanning a batch."""
	batch = await service.start_batch_scan(session, batch_id)
	if not batch:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
	return batch


@router.post("/{project_id}/batches/{batch_id}/record-page", response_model=ScanningBatch)
async def record_page_scan(
	project_id: str,
	batch_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Record one scanned page against a batch (increments scanned_pages counter)."""
	batch = await service.record_page_scan(session, batch_id)
	if not batch:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
	return batch


@router.post("/{project_id}/batches/{batch_id}/complete-scan", response_model=ScanningBatch)
async def complete_batch_scan(
	project_id: str,
	batch_id: str,
	actual_pages: int,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatch:
	"""Complete scanning a batch."""
	batch = await service.complete_batch_scan(session, batch_id, actual_pages)
	if not batch:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
	return batch


# =====================================================
# Batch Documents Endpoints
# =====================================================


@router.get("/{project_id}/batches/{batch_id}/documents", response_model=list[ScanningBatchDocument])
async def list_batch_documents(
	project_id: str,
	batch_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanningBatchDocument]:
	"""List all documents scanned in a batch."""
	docs = await service.get_batch_documents(session, batch_id)
	return list(docs)


@router.post(
	"/{project_id}/batches/{batch_id}/documents",
	response_model=ScanningBatchDocument,
	status_code=status.HTTP_201_CREATED,
)
async def add_batch_document(
	project_id: str,
	batch_id: str,
	data: ScanningBatchDocumentCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningBatchDocument:
	"""Add a scanned document to a batch."""
	return await service.add_document_to_batch(
		session=session,
		batch_id=batch_id,
		document_id=data.document_id,
		page_number=data.page_number,
		scan_job_id=data.scan_job_id,
		quality_score=data.quality_score,
		status=data.status,
		needs_review=data.needs_review,
		has_issues=data.has_issues,
		issue_details=data.issue_details,
	)


# =====================================================
# Milestones Endpoints
# =====================================================


@router.get("/{project_id}/milestones", response_model=list[ScanningMilestone])
async def list_milestones(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanningMilestone]:
	"""List all milestones for a project."""
	milestones = await service.get_project_milestones(session, project_id)
	return list(milestones)


@router.post(
	"/{project_id}/milestones",
	response_model=ScanningMilestone,
	status_code=status.HTTP_201_CREATED,
)
async def create_milestone(
	project_id: str,
	data: ScanningMilestoneCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningMilestone:
	"""Create a new milestone."""
	return await service.create_milestone(session, project_id, data)


@router.patch("/{project_id}/milestones/{milestone_id}", response_model=ScanningMilestone)
async def update_milestone(
	project_id: str,
	milestone_id: str,
	data: ScanningMilestoneUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningMilestone:
	"""Update a milestone."""
	milestone = await service.update_milestone(session, milestone_id, data)
	if not milestone:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found")
	return milestone


# =====================================================
# QC Endpoints
# =====================================================


@router.get("/{project_id}/qc/pending", response_model=list[QualityControlSample])
async def list_pending_qc_samples(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[QualityControlSample]:
	"""List pending QC samples for a project."""
	samples = await service.get_pending_qc_samples(session, project_id)
	return list(samples)


@router.post(
	"/{project_id}/qc/samples",
	response_model=QualityControlSample,
	status_code=status.HTTP_201_CREATED,
)
async def create_qc_sample(
	project_id: str,
	data: QualityControlSampleCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> QualityControlSample:
	"""Create a new QC sample."""
	return await service.create_qc_sample(session, data)


@router.patch("/{project_id}/qc/samples/{sample_id}", response_model=QualityControlSample)
async def update_qc_sample(
	project_id: str,
	sample_id: str,
	data: QualityControlSampleUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> QualityControlSample:
	"""Update a QC sample with review results."""
	sample = await service.update_qc_sample(
		session, sample_id, user.id, user.username, data
	)
	if not sample:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sample not found")
	return sample


# =====================================================
# Resources Endpoints
# =====================================================


@router.get("/resources", response_model=list[ScanningResource])
async def list_resources(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ScanningResource]:
	"""List all scanning resources."""
	resources = await service.get_resources(session, user.tenant_id)
	return list(resources)


@router.post(
	"/resources",
	response_model=ScanningResource,
	status_code=status.HTTP_201_CREATED,
)
async def create_resource(
	data: ScanningResourceCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningResource:
	"""Create a new resource."""
	return await service.create_resource(session, user.tenant_id, data)


@router.patch("/resources/{resource_id}", response_model=ScanningResource)
async def update_resource(
	resource_id: str,
	data: ScanningResourceUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningResource:
	"""Update a resource."""
	resource = await service.update_resource(session, resource_id, user.tenant_id, data)
	if not resource:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
	return resource


@router.delete("/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
	resource_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a resource."""
	deleted = await service.delete_resource(session, resource_id, user.tenant_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")


# =====================================================
# Phases Endpoints
# =====================================================


@router.get("/{project_id}/phases", response_model=list[ProjectPhase])
async def list_phases(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectPhase]:
	"""List all phases for a project."""
	phases = await service.get_project_phases(session, project_id)
	return list(phases)


@router.post(
	"/{project_id}/phases",
	response_model=ProjectPhase,
	status_code=status.HTTP_201_CREATED,
)
async def create_phase(
	project_id: str,
	data: ProjectPhaseCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectPhase:
	"""Create a new phase."""
	return await service.create_phase(session, project_id, data)


@router.patch("/{project_id}/phases/{phase_id}", response_model=ProjectPhase)
async def update_phase(
	project_id: str,
	phase_id: str,
	data: ProjectPhaseUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectPhase:
	"""Update a phase."""
	phase = await service.update_phase(session, phase_id, data)
	if not phase:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase not found")
	return phase


@router.delete("/{project_id}/phases/{phase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_phase(
	project_id: str,
	phase_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a phase."""
	deleted = await service.delete_phase(session, phase_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase not found")


# =====================================================
# Sessions Endpoints
# =====================================================


@router.get("/{project_id}/sessions", response_model=list[ScanningSession])
async def list_sessions(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	active_only: bool = Query(False, description="Only return active sessions"),
) -> list[ScanningSession]:
	"""List scanning sessions for a project."""
	sessions = await service.get_project_sessions(session, project_id, active_only)
	return list(sessions)


@router.post(
	"/{project_id}/sessions",
	response_model=ScanningSession,
	status_code=status.HTTP_201_CREATED,
)
async def start_session(
	project_id: str,
	data: ScanningSessionCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningSession:
	"""Start a new scanning session."""
	return await service.start_session(session, project_id, data)


@router.post("/{project_id}/sessions/{session_id}/end", response_model=ScanningSession)
async def end_session(
	project_id: str,
	session_id: str,
	data: ScanningSessionEnd,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningSession:
	"""End a scanning session."""
	scan_session = await service.end_session(session, session_id, data)
	if not scan_session:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
	return scan_session


# =====================================================
# Issues Endpoints
# =====================================================


@router.get("/{project_id}/issues", response_model=list[ProjectIssue])
async def list_issues(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	open_only: bool = Query(False, description="Only return open issues"),
) -> list[ProjectIssue]:
	"""List issues for a project."""
	issues = await service.get_project_issues(session, project_id, open_only)
	return list(issues)


@router.post(
	"/{project_id}/issues",
	response_model=ProjectIssue,
	status_code=status.HTTP_201_CREATED,
)
async def create_issue(
	project_id: str,
	data: ProjectIssueCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectIssue:
	"""Create a new issue."""
	return await service.create_issue(session, project_id, user.id, user.username, data)


@router.patch("/{project_id}/issues/{issue_id}", response_model=ProjectIssue)
async def update_issue(
	project_id: str,
	issue_id: str,
	data: ProjectIssueUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectIssue:
	"""Update an issue."""
	issue = await service.update_issue(session, issue_id, data)
	if not issue:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
	return issue


# =====================================================
# Snapshots & Metrics Endpoints
# =====================================================


@router.post("/{project_id}/snapshots", response_model=ProgressSnapshot)
async def create_snapshot(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgressSnapshot:
	"""Create a progress snapshot."""
	return await service.create_snapshot(session, project_id)


@router.get("/{project_id}/snapshots", response_model=list[ProgressSnapshot])
async def list_snapshots(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	limit: int = Query(100, ge=1, le=1000),
) -> list[ProgressSnapshot]:
	"""List progress snapshots for a project."""
	snapshots = await service.get_project_snapshots(session, project_id, limit)
	return list(snapshots)


@router.get("/{project_id}/daily-metrics", response_model=list[DailyProjectMetrics])
async def list_daily_metrics(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	start_date: date | None = None,
	end_date: date | None = None,
) -> list[DailyProjectMetrics]:
	"""List daily metrics for a project."""
	metrics = await service.get_daily_metrics(session, project_id, start_date, end_date)
	return list(metrics)


@router.get("/{project_id}/operator-metrics", response_model=list[OperatorDailyMetrics])
async def list_operator_metrics(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	operator_id: str | None = None,
	start_date: date | None = None,
	end_date: date | None = None,
) -> list[OperatorDailyMetrics]:
	"""List operator daily metrics for a project."""
	metrics = await service.get_operator_metrics(
		session, project_id, operator_id, start_date, end_date
	)
	return list(metrics)


# =====================================================
# AI Advisor Endpoints
# =====================================================


@router.get("/{project_id}/ai-analysis", response_model=AIAdvisorResponse)
async def get_ai_analysis(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> AIAdvisorResponse:
	"""Get AI-powered analysis and recommendations for a project."""
	advisor = get_project_advisor()
	return await advisor.analyze_project(session, project_id)


# =====================================================
# Reports Endpoints
# =====================================================


@router.get("/{project_id}/reports/daily")
async def get_daily_report(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	report_date: date | None = None,
	format: str = Query("html", pattern="^(html|pdf)$"),
):
	"""Generate a daily progress report."""
	from fastapi.responses import HTMLResponse, Response
	from .reports import generate_daily_report

	content = await generate_daily_report(session, project_id, report_date, format)

	if format == "pdf":
		return Response(
			content=content,
			media_type="application/pdf",
			headers={"Content-Disposition": f"attachment; filename=daily-report-{report_date or 'today'}.pdf"},
		)
	return HTMLResponse(content=content)


@router.get("/{project_id}/reports/weekly")
async def get_weekly_report(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	week_ending: date | None = None,
	format: str = Query("html", pattern="^(html|pdf)$"),
):
	"""Generate a weekly summary report."""
	from fastapi.responses import HTMLResponse, Response
	from .reports import generate_weekly_report

	content = await generate_weekly_report(session, project_id, week_ending, format)

	if format == "pdf":
		return Response(
			content=content,
			media_type="application/pdf",
			headers={"Content-Disposition": f"attachment; filename=weekly-report-{week_ending or 'current'}.pdf"},
		)
	return HTMLResponse(content=content)


# =====================================================
# AI Advisor Endpoints
# =====================================================

# In-process cache: project_id -> AIAdvisorResponse
_ai_advisor_cache: dict[str, AIAdvisorResponse] = {}


class PredictionAccuracy(BaseModel):
	metric: str
	predicted: float
	actual: float
	accuracy: float
	date: str


@router.get("/{project_id}/ai-advisor", response_model=AIAdvisorResponse)
async def get_ai_advisor(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> AIAdvisorResponse:
	"""Return latest AI advisor analysis; run if not yet cached."""
	if project_id not in _ai_advisor_cache:
		advisor = get_project_advisor()
		_ai_advisor_cache[project_id] = await advisor.analyze_project(session, project_id)
	return _ai_advisor_cache[project_id]


@router.post("/{project_id}/ai-advisor/analyze", response_model=AIAdvisorResponse)
async def run_ai_analysis(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> AIAdvisorResponse:
	"""Force a fresh AI analysis of the project."""
	advisor = get_project_advisor()
	result = await advisor.analyze_project(session, project_id)
	_ai_advisor_cache[project_id] = result
	return result


@router.get("/{project_id}/ai-advisor/history", response_model=list[PredictionAccuracy])
async def get_ai_advisor_history(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[PredictionAccuracy]:
	"""Return prediction accuracy history derived from daily metrics vs forecasts."""
	from sqlalchemy import select as sa_select
	from .models import DailyProjectMetricsModel, ScanningMilestoneModel
	from datetime import datetime as dt

	# Fetch last 14 days of daily metrics
	metrics_stmt = (
		sa_select(DailyProjectMetricsModel)
		.where(DailyProjectMetricsModel.project_id == project_id)
		.order_by(DailyProjectMetricsModel.metric_date.desc())
		.limit(14)
	)
	rows = (await session.execute(metrics_stmt)).scalars().all()
	if not rows:
		return []

	# Use pages_scanned as both predicted (from previous day's target) and actual
	history: list[PredictionAccuracy] = []
	for i, row in enumerate(rows[:-1]):
		prev = rows[i + 1]
		predicted = float(prev.pages_scanned or 0)
		actual = float(row.pages_scanned or 0)
		if predicted > 0:
			accuracy = min(100.0, (actual / predicted) * 100)
		else:
			accuracy = 100.0 if actual == 0 else 0.0
		history.append(PredictionAccuracy(
			metric="pages_scanned",
			predicted=predicted,
			actual=actual,
			accuracy=round(accuracy, 1),
			date=row.metric_date.isoformat(),
		))

	return history


@router.post(
	"/{project_id}/ai-advisor/recommendations/{recommendation_id}/apply",
	status_code=status.HTTP_200_OK,
)
async def apply_recommendation(
	project_id: str,
	recommendation_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
	"""Mark a recommendation as applied and log the action."""
	# Verify recommendation exists in cached analysis
	cached = _ai_advisor_cache.get(project_id)
	if cached:
		rec = next((r for r in cached.recommendations if r.id == recommendation_id), None)
		if rec is None:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")

	# Persist the apply event as a resolved project issue note
	from uuid6 import uuid7
	from .models import ProjectIssueModel
	from .views import ProjectIssueType, ProjectIssueSeverity, IssueStatus
	note = ProjectIssueModel(
		id=str(uuid7()),
		project_id=project_id,
		title=f"Applied AI recommendation: {recommendation_id[:8]}",
		description=f"Recommendation {recommendation_id} applied by {user.username}",
		issue_type=ProjectIssueType.OTHER.value,
		severity=ProjectIssueSeverity.LOW.value,
		status=IssueStatus.RESOLVED.value,
		reported_by_id=str(user.id),
		reported_by_name=user.username,
	)
	session.add(note)
	await session.commit()

	return {"project_id": project_id, "recommendation_id": recommendation_id, "applied": True}


# =====================================================
# Sub-Project Endpoints
# =====================================================


@router.get("/{project_id}/sub-projects", response_model=list[SubProject])
async def list_sub_projects(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[SubProject]:
	"""List all sub-projects for a project."""
	sub_projects = await service.get_sub_projects(session, project_id)
	return list(sub_projects)


@router.get("/{project_id}/sub-projects/{sub_project_id}", response_model=SubProject)
async def get_sub_project(
	project_id: str,
	sub_project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SubProject:
	"""Get a sub-project by ID."""
	sub_project = await service.get_sub_project(session, sub_project_id)
	if not sub_project:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sub-project not found")
	return sub_project


@router.post(
	"/{project_id}/sub-projects",
	response_model=SubProject,
	status_code=status.HTTP_201_CREATED,
)
async def create_sub_project(
	project_id: str,
	data: SubProjectCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SubProject:
	"""Create a new sub-project."""
	return await service.create_sub_project(session, project_id, data)


@router.patch("/{project_id}/sub-projects/{sub_project_id}", response_model=SubProject)
async def update_sub_project(
	project_id: str,
	sub_project_id: str,
	data: SubProjectUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SubProject:
	"""Update a sub-project."""
	sub_project = await service.update_sub_project(session, sub_project_id, data)
	if not sub_project:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sub-project not found")
	return sub_project


@router.delete("/{project_id}/sub-projects/{sub_project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sub_project(
	project_id: str,
	sub_project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a sub-project."""
	deleted = await service.delete_sub_project(session, sub_project_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sub-project not found")


# =====================================================
# Location Endpoints
# =====================================================


@router.get("/locations", response_model=list[ScanningLocation])
async def list_locations(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	active_only: bool = Query(True, description="Only return active locations"),
) -> list[ScanningLocation]:
	"""List all scanning locations for the tenant."""
	locations = await service.get_locations(session, user.tenant_id, active_only)
	return list(locations)


@router.get("/locations/{location_id}", response_model=ScanningLocation)
async def get_location(
	location_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningLocation:
	"""Get a location by ID."""
	location = await service.get_location(session, location_id, user.tenant_id)
	if not location:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")
	return location


@router.post(
	"/locations",
	response_model=ScanningLocation,
	status_code=status.HTTP_201_CREATED,
)
async def create_location(
	data: ScanningLocationCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningLocation:
	"""Create a new scanning location."""
	return await service.create_location(session, user.tenant_id, data)


@router.patch("/locations/{location_id}", response_model=ScanningLocation)
async def update_location(
	location_id: str,
	data: ScanningLocationUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ScanningLocation:
	"""Update a location."""
	location = await service.update_location(session, location_id, user.tenant_id, data)
	if not location:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")
	return location


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_location(
	location_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a location."""
	deleted = await service.delete_location(session, location_id, user.tenant_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location not found")


# =====================================================
# Shift Endpoints
# =====================================================


@router.get("/shifts", response_model=list[Shift])
async def list_shifts(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	location_id: str | None = None,
	active_only: bool = Query(True),
) -> list[Shift]:
	"""List all shifts for the tenant."""
	shifts = await service.get_shifts(session, user.tenant_id, location_id, active_only)
	return list(shifts)


@router.post(
	"/shifts",
	response_model=Shift,
	status_code=status.HTTP_201_CREATED,
)
async def create_shift(
	data: ShiftCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> Shift:
	"""Create a new shift."""
	return await service.create_shift(session, user.tenant_id, data)


@router.patch("/shifts/{shift_id}", response_model=Shift)
async def update_shift(
	shift_id: str,
	data: ShiftUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> Shift:
	"""Update a shift."""
	shift = await service.update_shift(session, shift_id, user.tenant_id, data)
	if not shift:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
	return shift


@router.get("/shift-assignments", response_model=list[ShiftAssignment])
async def list_shift_assignments(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	shift_id: str | None = None,
	operator_id: str | None = None,
	project_id: str | None = None,
	assignment_date: date | None = None,
	date_from: date | None = None,
	date_to: date | None = None,
) -> list[ShiftAssignment]:
	"""List shift assignments with optional filters."""
	assignments = await service.get_shift_assignments(
		session, shift_id, operator_id, assignment_date, project_id, date_from, date_to
	)
	return list(assignments)


@router.delete("/shift-assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shift_assignment(
	assignment_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Delete a shift assignment."""
	deleted = await service.delete_shift_assignment(session, assignment_id)
	if not deleted:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")


@router.post(
	"/shift-assignments",
	response_model=ShiftAssignment,
	status_code=status.HTTP_201_CREATED,
)
async def create_shift_assignment(
	data: ShiftAssignmentCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ShiftAssignment:
	"""Assign an operator to a shift."""
	return await service.create_shift_assignment(session, data)


@router.post("/shifts/assignments/bulk", response_model=list[ShiftAssignment])
async def bulk_create_shift_assignments(
	data: ShiftAssignmentBulkCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ShiftAssignment]:
	"""Bulk assign operators to shifts."""
	return await service.bulk_create_shift_assignments(session, data)


# =====================================================
# Cost Tracking Endpoints
# =====================================================


@router.get("/{project_id}/costs", response_model=list[ProjectCost])
async def list_project_costs(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	cost_type: CostType | None = None,
	start_date: date | None = None,
	end_date: date | None = None,
) -> list[ProjectCost]:
	"""List costs for a project."""
	costs = await service.get_project_costs(session, project_id, cost_type, start_date, end_date)
	return list(costs)


@router.post(
	"/{project_id}/costs",
	response_model=ProjectCost,
	status_code=status.HTTP_201_CREATED,
)
async def add_project_cost(
	project_id: str,
	data: ProjectCostCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectCost:
	"""Add a cost entry to a project."""
	return await service.add_project_cost(session, project_id, data)


@router.get("/{project_id}/costs/summary", response_model=CostSummary)
async def get_cost_summary(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> CostSummary:
	"""Get cost summary for a project."""
	return await service.get_cost_summary(session, project_id)


@router.get("/{project_id}/budget", response_model=ProjectBudget | None)
async def get_project_budget(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectBudget | None:
	"""Get budget for a project."""
	return await service.get_budget(session, project_id)


@router.post(
	"/{project_id}/budget",
	response_model=ProjectBudget,
	status_code=status.HTTP_201_CREATED,
)
async def create_project_budget(
	project_id: str,
	data: ProjectBudgetCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectBudget:
	"""Create a budget for a project."""
	return await service.create_budget(session, project_id, data)


@router.patch("/{project_id}/budget/{budget_id}", response_model=ProjectBudget)
async def update_project_budget(
	project_id: str,
	budget_id: str,
	data: ProjectBudgetUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectBudget:
	"""Update a project budget."""
	budget = await service.update_budget(session, budget_id, data, user.id if data.is_approved else None)
	if not budget:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
	return budget


# =====================================================
# SLA Endpoints
# =====================================================


@router.get("/{project_id}/slas", response_model=list[SLA])
async def list_project_slas(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[SLA]:
	"""List SLAs for a project."""
	slas = await service.get_project_slas(session, project_id)
	return list(slas)


@router.post(
	"/{project_id}/slas",
	response_model=SLA,
	status_code=status.HTTP_201_CREATED,
)
async def create_sla(
	project_id: str,
	data: SLACreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SLA:
	"""Create a new SLA."""
	return await service.create_sla(session, project_id, data)


@router.patch("/{project_id}/slas/{sla_id}", response_model=SLA)
async def update_sla(
	project_id: str,
	sla_id: str,
	data: SLAUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SLA:
	"""Update an SLA."""
	sla = await service.update_sla(session, sla_id, data)
	if not sla:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SLA not found")
	return sla


@router.post("/{project_id}/slas/{sla_id}/check", response_model=SLA)
async def check_sla_status(
	project_id: str,
	sla_id: str,
	current_value: float,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SLA:
	"""Check and update SLA status."""
	sla = await service.check_sla_status(session, sla_id, current_value)
	if not sla:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SLA not found")
	return sla


@router.get("/{project_id}/sla-alerts", response_model=list[SLAAlert])
async def list_sla_alerts(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	unacknowledged_only: bool = Query(False),
) -> list[SLAAlert]:
	"""List SLA alerts for a project."""
	alerts = await service.get_sla_alerts(session, project_id=project_id, unacknowledged_only=unacknowledged_only)
	return list(alerts)


@router.post("/{project_id}/sla-alerts/{alert_id}/acknowledge", response_model=SLAAlert)
async def acknowledge_sla_alert(
	project_id: str,
	alert_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	resolution_notes: str | None = None,
) -> SLAAlert:
	"""Acknowledge an SLA alert."""
	alert = await service.acknowledge_sla_alert(session, alert_id, user.id, resolution_notes)
	if not alert:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
	return alert


# =====================================================
# Equipment Maintenance Endpoints
# =====================================================


@router.get("/maintenance", response_model=list[EquipmentMaintenance])
async def list_maintenance(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	resource_id: str | None = None,
	status: MaintenanceStatus | None = None,
	upcoming_days: int | None = None,
) -> list[EquipmentMaintenance]:
	"""List maintenance schedules."""
	maintenance = await service.get_maintenance_schedule(session, resource_id, status, upcoming_days)
	return list(maintenance)


@router.post(
	"/maintenance",
	response_model=EquipmentMaintenance,
	status_code=status.HTTP_201_CREATED,
)
async def schedule_maintenance(
	data: EquipmentMaintenanceCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> EquipmentMaintenance:
	"""Schedule equipment maintenance."""
	return await service.schedule_maintenance(session, data)


@router.patch("/maintenance/{maintenance_id}", response_model=EquipmentMaintenance)
async def update_maintenance(
	maintenance_id: str,
	data: EquipmentMaintenanceUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> EquipmentMaintenance:
	"""Update maintenance record."""
	maintenance = await service.update_maintenance(session, maintenance_id, data)
	if not maintenance:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance record not found")
	return maintenance


# =====================================================
# Operator Certification Endpoints
# =====================================================


@router.get("/certifications", response_model=list[OperatorCertification])
async def list_certifications(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	operator_id: str | None = None,
	certification_type: str | None = None,
	active_only: bool = Query(True),
) -> list[OperatorCertification]:
	"""List operator certifications."""
	certs = await service.get_operator_certifications(
		session, operator_id, certification_type, active_only
	)
	return list(certs)


@router.post(
	"/certifications",
	response_model=OperatorCertification,
	status_code=status.HTTP_201_CREATED,
)
async def create_certification(
	data: OperatorCertificationCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> OperatorCertification:
	"""Create an operator certification."""
	return await service.create_certification(session, data)


@router.patch("/certifications/{certification_id}", response_model=OperatorCertification)
async def update_certification(
	certification_id: str,
	data: OperatorCertificationUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> OperatorCertification:
	"""Update an operator certification."""
	cert = await service.update_certification(session, certification_id, data)
	if not cert:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certification not found")
	return cert


@router.get("/certifications/expiring", response_model=list[OperatorCertification])
async def list_expiring_certifications(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	days: int = Query(30, ge=1, le=365),
) -> list[OperatorCertification]:
	"""List certifications expiring within specified days."""
	certs = await service.get_expiring_certifications(session, days)
	return list(certs)


# =====================================================
# Capacity Planning Endpoints
# =====================================================


@router.get("/{project_id}/capacity-plans", response_model=list[CapacityPlan])
async def list_capacity_plans(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[CapacityPlan]:
	"""List capacity plans for a project."""
	plans = await service.get_capacity_plans(session, project_id)
	return list(plans)


@router.post(
	"/{project_id}/capacity-plans",
	response_model=CapacityPlan,
	status_code=status.HTTP_201_CREATED,
)
async def create_capacity_plan(
	project_id: str,
	data: CapacityPlanCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> CapacityPlan:
	"""Create a capacity plan for a project."""
	return await service.create_capacity_plan(session, project_id, data, user.id)


# =====================================================
# Document Type Distribution Endpoints
# =====================================================


@router.get("/{project_id}/document-types", response_model=list[DocumentTypeDistribution])
async def list_document_type_distributions(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[DocumentTypeDistribution]:
	"""List document type distributions for a project."""
	dists = await service.get_document_type_distributions(session, project_id)
	return list(dists)


@router.post(
	"/{project_id}/document-types",
	response_model=DocumentTypeDistribution,
	status_code=status.HTTP_201_CREATED,
)
async def create_document_type_distribution(
	project_id: str,
	data: DocumentTypeDistributionCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentTypeDistribution:
	"""Create a document type distribution entry."""
	return await service.create_document_type_distribution(session, project_id, data)


@router.patch("/{project_id}/document-types/{distribution_id}", response_model=DocumentTypeDistribution)
async def update_document_type_distribution(
	project_id: str,
	distribution_id: str,
	data: DocumentTypeDistributionUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentTypeDistribution:
	"""Update a document type distribution entry."""
	dist = await service.update_document_type_distribution(session, distribution_id, data)
	if not dist:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Distribution not found")
	return dist


# =====================================================
# Priority Queue Endpoints
# =====================================================


@router.get("/{project_id}/priority-queue", response_model=list[BatchPriority])
async def get_priority_queue(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	rush_only: bool = Query(False),
) -> list[BatchPriority]:
	"""Get priority queue for batches in a project."""
	queue = await service.get_priority_queue(session, project_id, rush_only)
	return list(queue)


@router.post(
	"/batch-priority",
	response_model=BatchPriority,
	status_code=status.HTTP_201_CREATED,
)
async def set_batch_priority(
	data: BatchPriorityCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BatchPriority:
	"""Set priority for a batch."""
	return await service.set_batch_priority(session, data)


@router.patch("/batch-priority/{priority_id}", response_model=BatchPriority)
async def update_batch_priority(
	priority_id: str,
	data: BatchPriorityUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BatchPriority:
	"""Update batch priority."""
	priority = await service.update_batch_priority(session, priority_id, data)
	if not priority:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Priority entry not found")
	return priority


# =====================================================
# Contract Endpoints
# =====================================================


@router.get("/{project_id}/contracts", response_model=list[ProjectContract])
async def list_project_contracts(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectContract]:
	"""List contracts for a project."""
	contracts = await service.get_project_contracts(session, project_id)
	return list(contracts)


@router.post(
	"/{project_id}/contracts",
	response_model=ProjectContract,
	status_code=status.HTTP_201_CREATED,
)
async def create_contract(
	project_id: str,
	data: ProjectContractCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectContract:
	"""Create a project contract."""
	return await service.create_contract(session, project_id, data)


@router.patch("/{project_id}/contracts/{contract_id}", response_model=ProjectContract)
async def update_contract(
	project_id: str,
	contract_id: str,
	data: ProjectContractUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectContract:
	"""Update a project contract."""
	contract = await service.update_contract(session, contract_id, data)
	if not contract:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")
	return contract


# =====================================================
# Workload Forecast Endpoints
# =====================================================


@router.get("/{project_id}/workload-forecasts", response_model=list[WorkloadForecast])
async def list_workload_forecasts(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkloadForecast]:
	"""List workload forecasts for a project."""
	forecasts = await service.get_workload_forecasts(session, project_id)
	return list(forecasts)


@router.post(
	"/{project_id}/workload-forecasts",
	response_model=WorkloadForecast,
	status_code=status.HTTP_201_CREATED,
)
async def create_workload_forecast(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	forecast_period_start: date = Query(...),
	forecast_period_end: date = Query(...),
) -> WorkloadForecast:
	"""Create a workload forecast."""
	from datetime import datetime
	return await service.create_workload_forecast(
		session,
		project_id,
		datetime.combine(forecast_period_start, datetime.min.time()),
		datetime.combine(forecast_period_end, datetime.max.time()),
	)


# =====================================================
# Checkpoint Endpoints
# =====================================================


@router.get("/{project_id}/checkpoints", response_model=list[ProjectCheckpoint])
async def list_project_checkpoints(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectCheckpoint]:
	"""List checkpoints for a project."""
	checkpoints = await service.get_project_checkpoints(session, project_id)
	return list(checkpoints)


@router.post(
	"/{project_id}/checkpoints",
	response_model=ProjectCheckpoint,
	status_code=status.HTTP_201_CREATED,
)
async def create_checkpoint(
	project_id: str,
	data: ProjectCheckpointCreate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectCheckpoint:
	"""Create a project checkpoint."""
	return await service.create_checkpoint(session, project_id, data)


@router.patch("/{project_id}/checkpoints/{checkpoint_id}", response_model=ProjectCheckpoint)
async def update_checkpoint(
	project_id: str,
	checkpoint_id: str,
	data: ProjectCheckpointUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectCheckpoint:
	"""Update a checkpoint."""
	checkpoint = await service.update_checkpoint(
		session, checkpoint_id, data, user.id, user.username
	)
	if not checkpoint:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkpoint not found")
	return checkpoint


# =====================================================
# Bulk Operations Endpoints
# =====================================================


@router.post(
	"/{project_id}/batches/bulk-import",
	response_model=BulkOperationResult,
)
async def bulk_import_batches(
	project_id: str,
	data: BulkBatchImport,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BulkOperationResult:
	"""Bulk import batches for a project."""
	return await service.bulk_import_batches(session, project_id, data)


@router.post(
	"/batches/bulk-update",
	response_model=BulkOperationResult,
)
async def bulk_update_batches(
	data: BulkBatchUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BulkOperationResult:
	"""Bulk update batches."""
	return await service.bulk_update_batches(session, data)


# =====================================================
# Dashboard and Analytics Endpoints
# =====================================================


@router.get("/{project_id}/dashboard", response_model=ProjectDashboard)
async def get_project_dashboard(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectDashboard:
	"""Get comprehensive project dashboard data."""
	return await service.get_project_dashboard(session, project_id)


@router.get("/{project_id}/burndown", response_model=BurndownChart)
async def get_burndown_chart(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> BurndownChart:
	"""Get burndown chart data for a project."""
	return await service.get_burndown_chart(session, project_id)


@router.get("/{project_id}/velocity", response_model=VelocityChart)
async def get_velocity_chart(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	period_days: int = Query(30, ge=7, le=365),
) -> VelocityChart:
	"""Get velocity chart data for a project."""
	return await service.get_velocity_chart(session, project_id, period_days)


@router.get("/{project_id}/location-dashboard", response_model=MultiLocationDashboard)
async def get_multi_location_dashboard(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> MultiLocationDashboard:
	"""Get multi-location dashboard for a project."""
	return await service.get_multi_location_dashboard(session, project_id, user.tenant_id)

# =====================================================
# Gamification Endpoints
# =====================================================


@router.get("/gamification/leaderboard", response_model=list[OperatorDailyMetrics])
async def get_leaderboard(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
	limit: int = Query(10, ge=1, le=50),
) -> list[OperatorDailyMetrics]:
	"""Get the daily leaderboard."""
	return await service.get_leaderboard(session, user.tenant_id, limit)


@router.get("/gamification/performance", response_model=list[dict])
async def get_operator_performance(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
	"""Get hourly performance for the current operator."""
	return await service.get_hourly_performance(session, user.id)


# =====================================================
# Project-ID-free aliases (frontend doesn't always have project_id)
# =====================================================

@router.post("/sla-alerts/{alert_id}/acknowledge", response_model=SLAAlert)
async def acknowledge_sla_alert_no_project(
	alert_id: str,
	body: dict,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> SLAAlert:
	"""Acknowledge an SLA alert by alert ID alone."""
	resolution_notes = body.get("notes")
	alert = await service.acknowledge_sla_alert(session, alert_id, user.id, resolution_notes)
	if not alert:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
	return alert


@router.patch("/checkpoints/{checkpoint_id}", response_model=ProjectCheckpoint)
async def update_checkpoint_no_project(
	checkpoint_id: str,
	data: ProjectCheckpointUpdate,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectCheckpoint:
	"""Update a checkpoint by checkpoint ID alone."""
	checkpoint = await service.update_checkpoint(session, checkpoint_id, data, user.id, user.username)
	if not checkpoint:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkpoint not found")
	return checkpoint


@router.get("/location-dashboard", response_model=MultiLocationDashboard)
async def get_global_location_dashboard(
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
) -> MultiLocationDashboard:
	"""Get aggregated multi-location dashboard across all projects."""
	return await service.get_multi_location_dashboard(session, project_id=None, tenant_id=user.tenant_id)


# =====================================================
# Barcode Label Generation Endpoints
# =====================================================


class BarcodeLabelRequest(BaseModel):
	count: int
	batch_id: str | None = None
	format: str = "pdf"          # "pdf" | "png"
	label_size: str = "letter"   # "a4" | "letter"


@router.post("/{project_id}/barcode-labels")
async def generate_barcode_labels(
	project_id: str,
	body: BarcodeLabelRequest,
	user: Annotated[User, Depends(get_current_user)],
	session: Annotated[AsyncSession, Depends(get_db)],
):
	"""Generate sequential barcode labels for a scanning project.

	Returns a streaming PDF (format=pdf) or a ZIP archive of PNGs (format=png).
	Each label encodes a fresh document_id so physical documents can be tracked
	before they are scanned into the system.
	"""
	import io
	import zipfile
	from uuid6 import uuid7
	from fastapi.responses import StreamingResponse
	from reportlab.lib.pagesizes import A4, LETTER

	from papermerge.core.features.inventory.qr import LabelData, LabelSheetGenerator, QRCodeGenerator

	# Verify project exists
	project = await service.get_scanning_project(session, project_id, user.tenant_id)
	if not project:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

	page_size = A4 if body.label_size == "a4" else LETTER
	batch_id = body.batch_id or str(uuid7())

	labels = [
		LabelData(
			document_id=str(uuid7()),
			batch_id=batch_id,
			sequence_number=i + 1,
		)
		for i in range(body.count)
	]

	if body.format == "png":
		qr_gen = QRCodeGenerator(box_size=10, border=4)
		buf = io.BytesIO()
		with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
			for label in labels:
				img = qr_gen.generate_with_label(label)
				img_buf = io.BytesIO()
				img.save(img_buf, format="PNG")
				img_buf.seek(0)
				zf.writestr(f"label_{label.sequence_number:04d}.png", img_buf.read())
		buf.seek(0)

		return StreamingResponse(
			buf,
			media_type="application/zip",
			headers={
				"Content-Disposition": f'attachment; filename="barcode-labels-{batch_id}.zip"'
			},
		)
	else:
		# PDF output
		sheet_gen = LabelSheetGenerator(page_size=page_size)
		pdf_buf = io.BytesIO()

		# LabelSheetGenerator.generate_pdf writes to a path; wrap with a temp file
		import tempfile, os
		with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
			tmp_path = tmp.name

		try:
			sheet_gen.generate_pdf(labels, tmp_path, include_text=True)
			with open(tmp_path, "rb") as f:
				pdf_buf.write(f.read())
		finally:
			os.unlink(tmp_path)

		pdf_buf.seek(0)
		return StreamingResponse(
			pdf_buf,
			media_type="application/pdf",
			headers={
				"Content-Disposition": f'attachment; filename="barcode-labels-{batch_id}.pdf"'
			},
		)


# =====================================================
# Image Stitching Endpoints
# =====================================================


class StitchFromPathsRequest(BaseModel):
	image_paths: list[str]
	output_format: str = "jpeg"   # "jpeg" | "png" | "tiff"
	min_overlap: float = 0.15


@router.post("/stitch-images")
async def stitch_images_from_paths(
	body: StitchFromPathsRequest,
	user: Annotated[User, Depends(get_current_user)],
) -> "StreamingResponse":
	"""Stitch multiple overlapping document images from server-side paths.

	Request body:
	  - image_paths: list of absolute file paths accessible to the server
	  - output_format: "jpeg" | "png" | "tiff"  (default: "jpeg")
	  - min_overlap: fractional expected overlap between adjacent images (default: 0.15)

	Returns a StreamingResponse of the stitched image, or a 422/503 JSON error.
	"""
	import io
	from fastapi.responses import StreamingResponse as _SR

	from .stitching import (
		StitchStatus,
		_CV2_AVAILABLE,
		encode_image,
		stitch_document_images,
	)

	if not _CV2_AVAILABLE:
		from fastapi.responses import JSONResponse
		return JSONResponse(
			status_code=503,
			content={"detail": "opencv-python is not installed on this server"},
		)

	fmt = body.output_format.lower()
	if fmt not in ("jpeg", "jpg", "png", "tiff", "tif"):
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail=f"Unsupported output_format {body.output_format!r}; choose jpeg, png, or tiff",
		)

	if len(body.image_paths) < 2:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="At least 2 image_paths are required",
		)
	if len(body.image_paths) > 8:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="Maximum 8 images per stitch request",
		)

	paths = [Path(p) for p in body.image_paths]
	for p in paths:
		if not p.exists():
			raise HTTPException(
				status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
				detail=f"Image not found: {p}",
			)

	result = stitch_document_images(paths, min_overlap=body.min_overlap)

	if result.status != StitchStatus.OK or result.image is None:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={
				"status": result.status,
				"error": result.error_message,
				"images_used": result.images_used,
			},
		)

	media_type_map = {
		"jpeg": "image/jpeg",
		"jpg": "image/jpeg",
		"png": "image/png",
		"tiff": "image/tiff",
		"tif": "image/tiff",
	}
	img_bytes = encode_image(result.image, fmt)
	return _SR(
		content=io.BytesIO(img_bytes),
		media_type=media_type_map[fmt],
		headers={
			"X-Stitch-Status": result.status,
			"X-Stitch-Confidence": str(result.confidence),
			"X-Stitch-Images-Used": str(result.images_used),
		},
	)


@router.post("/stitch-images/from-uploads")
async def stitch_images_from_uploads(
	user: Annotated[User, Depends(get_current_user)],
	files: Annotated[list[UploadFile], File(description="2–8 overlapping document images")],
	output_format: Annotated[str, Form()] = "jpeg",
	min_overlap: Annotated[float, Form()] = 0.15,
) -> "StreamingResponse":
	"""Stitch uploaded images (multipart/form-data).

	Form fields:
	  - files[]: 2–8 image files (JPEG, PNG, TIFF)
	  - output_format: "jpeg" | "png" | "tiff"  (default: "jpeg")
	  - min_overlap: float  (default: 0.15)

	Returns a StreamingResponse of the stitched image, or a 422/503 JSON error.
	"""
	import io
	import os
	import tempfile
	from fastapi.responses import StreamingResponse as _SR

	from .stitching import (
		StitchStatus,
		_CV2_AVAILABLE,
		encode_image,
		stitch_document_images,
	)

	if not _CV2_AVAILABLE:
		from fastapi.responses import JSONResponse
		return JSONResponse(
			status_code=503,
			content={"detail": "opencv-python is not installed on this server"},
		)

	fmt = output_format.lower()
	if fmt not in ("jpeg", "jpg", "png", "tiff", "tif"):
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail=f"Unsupported output_format {output_format!r}",
		)

	if len(files) < 2:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="At least 2 files are required",
		)
	if len(files) > 8:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail="Maximum 8 files per stitch request",
		)

	# Write uploads to temp files so OpenCV can read them
	tmp_paths: list[Path] = []
	try:
		for upload in files:
			suffix = Path(upload.filename or "image.jpg").suffix or ".jpg"
			with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
				content = await upload.read()
				tmp.write(content)
				tmp_paths.append(Path(tmp.name))

		result = stitch_document_images(tmp_paths, min_overlap=min_overlap)
	finally:
		for p in tmp_paths:
			try:
				os.unlink(p)
			except OSError:
				pass

	if result.status != StitchStatus.OK or result.image is None:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={
				"status": result.status,
				"error": result.error_message,
				"images_used": result.images_used,
			},
		)

	media_type_map = {
		"jpeg": "image/jpeg",
		"jpg": "image/jpeg",
		"png": "image/png",
		"tiff": "image/tiff",
		"tif": "image/tiff",
	}
	img_bytes = encode_image(result.image, fmt)
	return _SR(
		content=io.BytesIO(img_bytes),
		media_type=media_type_map[fmt],
		headers={
			"X-Stitch-Status": result.status,
			"X-Stitch-Confidence": str(result.confidence),
			"X-Stitch-Images-Used": str(result.images_used),
		},
	)


# ── Project Export ───────────────────────────────────────────────────────────

@router.get("/{project_id}/export.csv")
async def export_project_csv(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
):
	"""Download a CSV manifest of all batches and their scan progress."""
	import csv
	import io
	from fastapi.responses import StreamingResponse as _SR
	from .models import ScanningProjectModel, ScanningBatchModel

	proj_row = await db.execute(select(ScanningProjectModel).where(ScanningProjectModel.id == project_id))
	project = proj_row.scalar_one_or_none()
	if not project:
		raise HTTPException(status_code=404, detail="Project not found")

	batches_row = await db.execute(
		select(ScanningBatchModel)
		.where(ScanningBatchModel.project_id == project_id)
		.order_by(ScanningBatchModel.batch_number)
	)
	batches = batches_row.scalars().all()

	buf = io.StringIO()
	writer = csv.writer(buf)
	writer.writerow([
		"batch_number", "status", "physical_location",
		"estimated_pages", "actual_pages", "scanned_pages",
		"assigned_operator", "assigned_scanner", "started_at", "completed_at",
	])
	for b in batches:
		writer.writerow([
			b.batch_number, b.status, b.physical_location,
			b.estimated_pages, b.actual_pages, b.scanned_pages,
			b.assigned_operator_name or "", b.assigned_scanner_name or "",
			b.started_at.isoformat() if b.started_at else "",
			b.completed_at.isoformat() if b.completed_at else "",
		])

	buf.seek(0)
	filename = f"{project.code}-batches.csv"
	return _SR(
		iter([buf.getvalue()]),
		media_type="text/csv",
		headers={"Content-Disposition": f'attachment; filename="{filename}"'},
	)


# ── Batch Manipulation (path-level, no project_id) ───────────────────────────
# VirtualRebundler calls /scanning-projects/batches/{id}/...

class _BatchReorderRequest(BaseModel):
	document_ids: list[str]

class _BatchMoveDocRequest(BaseModel):
	document_id: str
	target_batch_id: str

class _BatchSplitRequest(BaseModel):
	split_at_index: int

class _BatchMergeRequest(BaseModel):
	source_batch_id: str


@router.get("/batches/{batch_id}")
async def get_batch_by_id(
	batch_id: str,
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
	"""Return a batch with its ordered document list."""
	from .models import ScanningBatchModel, ScanningBatchDocumentModel

	row = await db.execute(select(ScanningBatchModel).where(ScanningBatchModel.id == batch_id))
	batch = row.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	docs_row = await db.execute(
		select(ScanningBatchDocumentModel)
		.where(ScanningBatchDocumentModel.batch_id == batch_id)
		.order_by(ScanningBatchDocumentModel.page_number)
	)
	docs = docs_row.scalars().all()

	return {
		"id": str(batch.id),
		"name": batch.batch_number,
		"status": batch.status,
		"documents": [
			{
				"id": str(d.id),
				"documentId": str(d.document_id),
				"order": d.page_number,
				"pageCount": 1,
				"fileName": None,
			}
			for d in docs
		],
	}


@router.post("/batches/{batch_id}/reorder", status_code=204)
async def reorder_batch_documents(
	batch_id: str,
	body: _BatchReorderRequest,
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Reorder documents within a batch by providing the new ordered list of IDs."""
	from .models import ScanningBatchDocumentModel
	from sqlalchemy import update as sa_update

	for new_order, doc_id in enumerate(body.document_ids):
		await db.execute(
			sa_update(ScanningBatchDocumentModel)
			.where(
				ScanningBatchDocumentModel.id == doc_id,
				ScanningBatchDocumentModel.batch_id == batch_id,
			)
			.values(page_number=new_order)
		)
	await db.commit()


@router.post("/batches/{batch_id}/move-document", status_code=204)
async def move_batch_document(
	batch_id: str,
	body: _BatchMoveDocRequest,
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Move a document from this batch to another batch."""
	from .models import ScanningBatchDocumentModel
	from sqlalchemy import update as sa_update

	await db.execute(
		sa_update(ScanningBatchDocumentModel)
		.where(
			ScanningBatchDocumentModel.id == body.document_id,
			ScanningBatchDocumentModel.batch_id == batch_id,
		)
		.values(batch_id=body.target_batch_id)
	)
	await db.commit()


@router.post("/batches/{batch_id}/split")
async def split_batch(
	batch_id: str,
	body: _BatchSplitRequest,
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
	"""Split a batch at a document index, creating a new batch for documents from that index on."""
	from .models import ScanningBatchModel, ScanningBatchDocumentModel
	from sqlalchemy import update as sa_update
	import uuid as _uuid

	row = await db.execute(select(ScanningBatchModel).where(ScanningBatchModel.id == batch_id))
	batch = row.scalar_one_or_none()
	if not batch:
		raise HTTPException(status_code=404, detail="Batch not found")

	docs_row = await db.execute(
		select(ScanningBatchDocumentModel)
		.where(ScanningBatchDocumentModel.batch_id == batch_id)
		.order_by(ScanningBatchDocumentModel.page_number)
	)
	docs = docs_row.scalars().all()

	split_at = body.split_at_index
	if split_at <= 0 or split_at >= len(docs):
		raise HTTPException(status_code=422, detail=f"split_at_index must be between 1 and {len(docs) - 1}")

	# Create new batch
	new_batch = ScanningBatchModel(
		id=_uuid.uuid4(),
		project_id=batch.project_id,
		batch_number=f"{batch.batch_number}-B",
		type=batch.type,
		physical_location=batch.physical_location,
		estimated_pages=len(docs) - split_at,
		status="pending",
		created_at=batch.created_at,
	)
	db.add(new_batch)
	await db.flush()

	# Move tail documents to new batch
	tail_ids = [str(d.id) for d in docs[split_at:]]
	if tail_ids:
		await db.execute(
			sa_update(ScanningBatchDocumentModel)
			.where(ScanningBatchDocumentModel.id.in_(tail_ids))
			.values(batch_id=new_batch.id)
		)
	await db.commit()

	return {"new_batch_id": str(new_batch.id), "new_batch_name": new_batch.batch_number}


@router.post("/batches/{batch_id}/merge", status_code=204)
async def merge_batches(
	batch_id: str,
	body: _BatchMergeRequest,
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
	"""Merge a source batch into this batch (source batch is deleted after merge)."""
	from .models import ScanningBatchDocumentModel
	from sqlalchemy import update as sa_update, delete as sa_delete

	# Find max page_number in target batch
	from sqlalchemy import func as sa_func
	max_row = await db.execute(
		select(sa_func.max(ScanningBatchDocumentModel.page_number))
		.where(ScanningBatchDocumentModel.batch_id == batch_id)
	)
	max_order = max_row.scalar() or -1

	# Fetch source docs ordered
	src_docs_row = await db.execute(
		select(ScanningBatchDocumentModel)
		.where(ScanningBatchDocumentModel.batch_id == body.source_batch_id)
		.order_by(ScanningBatchDocumentModel.page_number)
	)
	src_docs = src_docs_row.scalars().all()

	for i, doc in enumerate(src_docs):
		await db.execute(
			sa_update(ScanningBatchDocumentModel)
			.where(ScanningBatchDocumentModel.id == str(doc.id))
			.values(batch_id=batch_id, page_number=max_order + 1 + i)
		)

	# Delete now-empty source batch
	from .models import ScanningBatchModel
	await db.execute(
		sa_delete(ScanningBatchModel)
		.where(ScanningBatchModel.id == body.source_batch_id)
	)
	await db.commit()


# ── Quality Config ────────────────────────────────────────────────────────────

@router.get("/{project_id}/quality-config", response_model=QualityConfig)
async def get_quality_config(
	project_id: str,
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> QualityConfig:
	"""Return the current quality configuration for a scanning project."""
	row = await db.execute(
		select(ScanningProjectModel).where(ScanningProjectModel.id == project_id)
	)
	project = row.scalar_one_or_none()
	if not project:
		raise HTTPException(status_code=404, detail="Project not found")
	if project.quality_config:
		return QualityConfig.model_validate(project.quality_config)
	return QualityConfig()


@router.put("/{project_id}/quality-config", response_model=QualityConfig)
async def update_quality_config(
	project_id: str,
	config: QualityConfig,
	user: Annotated[User, Depends(get_current_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> QualityConfig:
	"""Replace the quality configuration for a scanning project."""
	row = await db.execute(
		select(ScanningProjectModel).where(ScanningProjectModel.id == project_id)
	)
	project = row.scalar_one_or_none()
	if not project:
		raise HTTPException(status_code=404, detail="Project not found")
	project.quality_config = config.model_dump()
	await db.commit()
	return config


# ── Camera Capture → Document ─────────────────────────────────────────────────

@router.post("/camera/capture", status_code=201)
async def camera_capture_to_document(
	user: Annotated[User, Depends(get_current_user)],
	image: UploadFile = File(..., description="Captured image (JPEG/PNG)"),
	folder_id: str | None = Form(default=None),
	title: str | None = Form(default=None),
	lang: str = Form(default="eng"),
	project_id: str | None = Form(default=None),
) -> dict:
	"""
	Ingest a camera-captured image as a document.

	Accepts a raw image upload, writes it to storage, creates a Document
	record, and queues OCR — identical pipeline to scanner ingest.
	"""
	import uuid as _uuid
	from papermerge.core import pathlib as pmg_pathlib
	from papermerge.core.db.engine import get_async_session_maker
	from papermerge.core.features.document.db import api as doc_dbapi
	from papermerge.core.features.document import schema as doc_schema
	from papermerge.core.types import MimeType
	from papermerge.storage.base import get_storage_backend
	from papermerge.core.tasks import send_task

	content_type = (image.content_type or "image/jpeg").lower()
	if "jpeg" in content_type or "jpg" in content_type:
		mime = MimeType.image_jpeg
		ext = "jpg"
	elif "png" in content_type:
		mime = MimeType.image_png
		ext = "png"
	elif "tiff" in content_type:
		mime = MimeType.image_tiff
		ext = "tiff"
	else:
		mime = MimeType.application_pdf
		ext = "pdf"

	data = await image.read()
	doc_id = _uuid.uuid4()
	doc_ver_id = _uuid.uuid4()
	safe_title = title or (image.filename or f"camera_{doc_id.hex[:8]}")
	file_name = f"{_uuid.uuid4().hex[:8]}_{safe_title.rsplit('.', 1)[0]}.{ext}"
	object_key = str(pmg_pathlib.docver_path(doc_ver_id, file_name=file_name))

	storage = get_storage_backend()
	await storage.upload_bytes(data=data, object_key=object_key, content_type=mime.value)

	session_maker = get_async_session_maker()
	async with session_maker() as session:
		new_doc = doc_schema.NewDocument(
			id=doc_id,
			title=safe_title,
			lang=lang,
			parent_id=_uuid.UUID(folder_id) if folder_id else None,
			ocr=True,
			file_name=file_name,
			created_by=user.id,
			updated_by=user.id,
		)
		doc = await doc_dbapi.create_document(
			session,
			new_doc,
			mime_type=mime,
			document_version_id=doc_ver_id,
		)
		await session.commit()

	send_task(
		"process_upload",
		kwargs={
			"document_id": str(doc_id),
			"document_version_id": str(doc_ver_id),
			"lang": lang,
			"user_id": str(user.id),
		},
		route_name="s3",
	)

	return {
		"documentId": str(doc_id),
		"documentVersionId": str(doc_ver_id),
		"fileName": file_name,
		"mimeType": mime.value,
		"sizeBytes": len(data),
		"projectId": project_id,
	}


# Route ordering fix: static collection paths (/resources, /locations, /shifts,
# /shift-assignments, /gamification, /batch-priority) must precede /{project_id}
# so FastAPI doesn't match them as project ID values.
_STATIC_PREFIXES = (
	"/scanning-projects/resources",
	"/scanning-projects/locations",
	"/scanning-projects/shifts",
	"/scanning-projects/shift-assignments",
	"/scanning-projects/gamification",
	"/scanning-projects/batch-priority",
	"/scanning-projects/sla-alerts",
	"/scanning-projects/checkpoints",
	"/scanning-projects/location-dashboard",
	"/scanning-projects/maintenance",
	"/scanning-projects/certifications",
	"/scanning-projects/stitch-images",
	"/scanning-projects/batches",
	"/scanning-projects/supervisor",
	"/scanning-projects/camera",
)
_static_routes = [
	r for r in router.routes
	if any(getattr(r, "path", "").startswith(p) for p in _STATIC_PREFIXES)
]
_other_routes = [r for r in router.routes if r not in _static_routes]
router.routes = _static_routes + _other_routes
