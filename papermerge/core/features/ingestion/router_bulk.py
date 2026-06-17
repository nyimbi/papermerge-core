# (c) Copyright Datacraft, 2026
"""ZIP/Folder bulk import endpoint.

POST /ingestion/bulk-upload  — accept a ZIP, extract, fan-out process_upload per file
GET  /ingestion/bulk-upload/{job_id} — poll status

Job state is tracked in Redis HSET (no ORM migration needed).
Key: bulk_upload:{job_id}
Fields: status, total_files, processed, failed, created_at, completed_at, tenant_id, failures (JSON)
"""
import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Depends, status
from pydantic import BaseModel

from papermerge.core.features.auth.dependencies import require_scopes
from papermerge.core.features.auth import scopes

logger = logging.getLogger(__name__)

router = APIRouter(
	prefix="/ingestion",
	tags=["ingestion"],
)

# ---------------------------------------------------------------------------
# Allowed document extensions
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = {
	".pdf", ".tiff", ".tif", ".jpg", ".jpeg", ".png",
	".docx", ".xlsx", ".odt", ".ods",
}


# ---------------------------------------------------------------------------
# Redis helpers — graceful no-op when Redis is absent
# ---------------------------------------------------------------------------

def _get_redis():
	"""Return a redis.Redis instance or None if unavailable."""
	try:
		from papermerge.core.config import get_settings
		settings = get_settings()
		broker_url = getattr(settings, "broker_url", None) or os.environ.get("CELERY_BROKER_URL", "")
		if not broker_url or not broker_url.startswith("redis"):
			return None
		import redis as _redis
		client = _redis.from_url(broker_url, decode_responses=True)
		client.ping()
		return client
	except Exception:
		return None


def _job_key(job_id: str) -> str:
	return f"bulk_upload:{job_id}"


def _write_job(r, job_id: str, data: dict) -> None:
	if r is None:
		return
	r.hset(_job_key(job_id), mapping={k: str(v) for k, v in data.items()})
	# Keep for 7 days
	r.expire(_job_key(job_id), 7 * 24 * 3600)


def _read_job(r, job_id: str) -> dict | None:
	if r is None:
		return None
	data = r.hgetall(_job_key(job_id))
	return data if data else None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class BulkUploadResponse(BaseModel):
	job_id: str
	total_files: int
	status: str
	status_url: str


class BulkUploadStatus(BaseModel):
	job_id: str
	status: str  # queued | processing | completed | partial | failed
	total_files: int
	processed: int
	failed: int
	created_at: str
	completed_at: Optional[str] = None
	failures: list[dict] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
	"/bulk-upload",
	status_code=status.HTTP_202_ACCEPTED,
	response_model=BulkUploadResponse,
)
async def bulk_upload(
	file: UploadFile = File(..., description="ZIP archive containing documents"),
	destination_folder_id: Optional[str] = Form(default=None),
	project_id: Optional[str] = Form(default=None),
	user: require_scopes(scopes.NODE_CREATE) = Depends(),
):
	"""Accept a ZIP archive, extract files, and fan out one Celery task per document."""
	if not file.filename or not file.filename.lower().endswith(".zip"):
		raise HTTPException(status_code=400, detail="Only .zip files accepted")

	job_id = str(uuid.uuid4())
	extract_dir = Path(tempfile.mkdtemp(prefix=f"bulk_upload_{job_id}_"))

	try:
		# Save upload to a temp file
		zip_tmp = extract_dir / "upload.zip"
		content = await file.read()
		zip_tmp.write_bytes(content)

		# Validate + extract
		if not zipfile.is_zipfile(zip_tmp):
			raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive")

		with zipfile.ZipFile(zip_tmp, "r") as zf:
			# Guard against zip-slip
			for member in zf.infolist():
				member_path = (extract_dir / member.filename).resolve()
				if not str(member_path).startswith(str(extract_dir.resolve())):
					raise HTTPException(status_code=400, detail="ZIP contains unsafe path traversal entries")
			zf.extractall(extract_dir)

		zip_tmp.unlink()

		# Collect eligible files recursively
		eligible: list[Path] = []
		for root, _dirs, files in os.walk(extract_dir):
			for fname in files:
				fp = Path(root) / fname
				if fp.suffix.lower() in ALLOWED_EXTENSIONS:
					eligible.append(fp)

		total_files = len(eligible)
		if total_files == 0:
			shutil.rmtree(extract_dir, ignore_errors=True)
			raise HTTPException(
				status_code=422,
				detail=(
					"ZIP contains no supported documents. "
					f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
				),
			)

		# Write initial job state to Redis
		now_iso = datetime.now(timezone.utc).isoformat()
		r = _get_redis()
		_write_job(r, job_id, {
			"status": "queued",
			"total_files": total_files,
			"processed": 0,
			"failed": 0,
			"created_at": now_iso,
			"completed_at": "",
			"tenant_id": str(user.tenant_id),
			"failures": "[]",
		})

		# Fan out one Celery task per file
		from papermerge.core.tasks import send_task

		for fp in eligible:
			send_task(
				"darchiva.ingestion.process_bulk_file",
				kwargs={
					"job_id": job_id,
					"file_path": str(fp),
					"file_name": fp.name,
					"file_size": fp.stat().st_size,
					"destination_folder_id": destination_folder_id,
					"project_id": project_id,
					"tenant_id": str(user.tenant_id),
					"user_id": str(user.id),
					"total_files": total_files,
				},
			)

		logger.info(
			"bulk_upload: job=%s total=%d tenant=%s",
			job_id[:8], total_files, str(user.tenant_id)[:8],
		)

	except HTTPException:
		shutil.rmtree(extract_dir, ignore_errors=True)
		raise
	except Exception as exc:
		shutil.rmtree(extract_dir, ignore_errors=True)
		logger.error("bulk_upload: unexpected error: %s", exc, exc_info=True)
		raise HTTPException(status_code=500, detail=str(exc))

	return BulkUploadResponse(
		job_id=job_id,
		total_files=total_files,
		status="queued",
		status_url=f"/api/v1/ingestion/bulk-upload/{job_id}",
	)


@router.get(
	"/bulk-upload/{job_id}",
	response_model=BulkUploadStatus,
)
async def bulk_upload_status(
	job_id: str,
	user: require_scopes(scopes.NODE_VIEW) = Depends(),
):
	"""Poll the status of a bulk upload job."""
	r = _get_redis()
	data = _read_job(r, job_id)
	if data is None:
		raise HTTPException(status_code=404, detail="Bulk upload job not found")

	# Validate tenant ownership
	if data.get("tenant_id") and data["tenant_id"] != str(user.tenant_id):
		raise HTTPException(status_code=403, detail="Not authorised to view this job")

	failures: list[dict] = []
	try:
		failures = json.loads(data.get("failures", "[]"))
	except (json.JSONDecodeError, ValueError):
		pass

	return BulkUploadStatus(
		job_id=job_id,
		status=data.get("status", "unknown"),
		total_files=int(data.get("total_files", 0)),
		processed=int(data.get("processed", 0)),
		failed=int(data.get("failed", 0)),
		created_at=data.get("created_at", ""),
		completed_at=data.get("completed_at") or None,
		failures=failures,
	)
