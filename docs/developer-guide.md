# dArchiva Developer Guide

## Table of Contents

1. [Overview](#overview)
2. [Repository Layout](#repository-layout)
3. [Prerequisites](#prerequisites)
4. [Local Development Setup](#local-development-setup)
5. [Configuration Reference](#configuration-reference)
6. [Architecture Deep-Dive](#architecture-deep-dive)
7. [Feature Module System](#feature-module-system)
8. [Adding a New Feature](#adding-a-new-feature)
9. [Authentication & Authorization](#authentication--authorization)
10. [Database Layer](#database-layer)
11. [Background Tasks & Celery](#background-tasks--celery)
12. [Workflow Engine (Prefect)](#workflow-engine-prefect)
13. [Storage Layer](#storage-layer)
14. [Testing](#testing)
15. [Code Conventions](#code-conventions)
16. [Deployment](#deployment)

---

## Overview

dArchiva is an enterprise document management platform with a 42-router FastAPI backend, async SQLAlchemy ORM on PostgreSQL 17+pgvector, Celery workers for OCR and background tasks, and Prefect for orchestrated approval workflows. The codebase is Python 3.13+ (uses `str | None` union syntax, `match`, `asyncio.TaskGroup`).

---

## Repository Layout

```
papermerge-core/
├── papermerge/
│   ├── app.py                    # FastAPI app factory
│   ├── cli.py                    # CLI entry point (pm command)
│   ├── config.py                 # pydantic-settings config model
│   ├── core/
│   │   ├── auth/                 # JWT logic, scope constants
│   │   ├── constants.py          # Celery task name constants
│   │   ├── db/
│   │   │   ├── engine.py         # Async engine + get_session dep
│   │   │   ├── base.py           # SQLAlchemy declarative Base
│   │   │   └── models.py         # Re-exports for convenience
│   │   ├── features/             # 42 feature modules (one dir each)
│   │   │   ├── <feature>/
│   │   │   │   ├── router.py     # FastAPI APIRouter
│   │   │   │   ├── schema.py     # Pydantic v2 request/response models
│   │   │   │   ├── service.py    # Business logic
│   │   │   │   └── db/
│   │   │   │       ├── orm.py    # SQLAlchemy ORM models
│   │   │   │       └── api.py    # DB-layer async functions
│   │   ├── router_loader.py      # Auto-discovers and includes all routers
│   │   ├── services/             # Cross-feature services (ingestion, etc.)
│   │   ├── tasks.py              # Celery task dispatch helpers
│   │   └── utils.py              # Shared utilities
│   └── storage/                  # Storage backends (local, S3, MinIO)
├── tests/
│   ├── features/                 # Per-feature test suites
│   └── conftest.py
├── alembic/                      # Database migrations
├── docs/                         # This directory
├── pyproject.toml
└── README.md
```

---

## Prerequisites

| Dependency | Minimum version | Notes |
|---|---|---|
| Python | 3.13 | 3.14 recommended |
| PostgreSQL | 17 | pgvector extension required |
| Redis | 7 | Celery broker + result backend |
| Node.js | 20 | Frontend only (darchiva-ui/) |

### System packages (macOS)

```bash
brew install postgresql@17 redis python@3.14
brew services start postgresql@17 redis
psql postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### System packages (Debian/Ubuntu)

```bash
apt install postgresql-17 postgresql-17-pgvector redis-server python3.14 python3.14-venv
```

---

## Local Development Setup

```bash
# 1. Clone
git clone https://github.com/nyimbi/papermerge-core.git
cd papermerge-core

# 2. Virtual environment (Python 3.14)
python3.14 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies (all extras for local dev)
pip install -e ".[quality,scanner,cloud_storage]"
pip install pytest pytest-asyncio pytest-mock

# 4. Create database
createdb darchiva
psql darchiva -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 5. Configure environment
cat > .env << 'EOF'
PM_DB_URL=postgresql+asyncpg://postgres:postgres@localhost/darchiva
PM_SECURITY__SECRET_KEY=dev-secret-key-change-in-prod
PM_REDIS_URL=redis://localhost:6379/0
EOF

# 6. Run migrations
alembic upgrade head

# 7. Start API server
fastapi dev papermerge/app.py

# 8. In a second terminal — start Celery worker
celery -A config worker -c 4 --loglevel=info

# 9. In a third terminal — start Prefect server (for workflows)
prefect server start
```

API: `http://localhost:8000`
Swagger UI: `http://localhost:8000/docs`

---

## Configuration Reference

All settings live in `papermerge/config.py` and are loaded via pydantic-settings. Env vars use double-underscore as a nested separator.

```bash
# Database
PM_DB_URL=postgresql+asyncpg://user:pass@host/db

# Security
PM_SECURITY__SECRET_KEY=<64-char hex>
PM_SECURITY__TOKEN_EXPIRE_MINUTES=60
PM_SECURITY__REFRESH_TOKEN_EXPIRE_DAYS=30

# Redis / Celery
PM_REDIS_URL=redis://:password@host:6379/0

# API
PM_API_PREFIX=/api/v1          # prefix for all routes; set to "" for root

# Storage — local filesystem
PM_STORAGE__TYPE=local
PM_STORAGE__LOCAL__PATH=/data/documents

# Storage — S3 / MinIO / R2
PM_STORAGE__TYPE=s3
PM_STORAGE__S3__ENDPOINT_URL=https://s3.amazonaws.com
PM_STORAGE__S3__BUCKET=darchiva-docs
PM_STORAGE__S3__ACCESS_KEY_ID=<key>
PM_STORAGE__S3__SECRET_ACCESS_KEY=<secret>

# OCR
PM_OCR__ENGINE=tesseract          # tesseract | qwen-vl | auto
PM_OCR__OLLAMA_URL=http://localhost:11434

# Email ingestion
PM_EMAIL__IMAP_HOST=mail.example.com
PM_EMAIL__IMAP_PORT=993
```

---

## Architecture Deep-Dive

### Request Lifecycle

```
HTTP Request
  → FastAPI middleware (CORS, logging)
  → JWT authentication (get_current_user dep)
  → Scope check (Security(get_current_user, scopes=[...]))
  → Route handler
    → DB session injected (get_session dep)
    → Business logic (service.py or inline)
    → Pydantic response model validation
  → HTTP Response
```

### Async-First Design

Every database operation is async via SQLAlchemy 2.0 async sessions. The `get_session` dependency yields an `AsyncSession` that is committed/rolled-back automatically:

```python
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            yield session
```

Routers use `Depends(get_session)` — never instantiate sessions directly.

### Multi-Tenancy

Tenant isolation is enforced at the query level. Every query against tenant-scoped resources includes a `WHERE tenant_id = user.tenant_id` filter. ORM models that carry tenant data have a `tenant_id: Mapped[UUID]` column. The middleware never filters globally — tenant ID comes from the JWT claim on the authenticated user.

Ownership of documents, tags, custom fields, and document types is tracked in the `ownerships` table (`owner_type`, `owner_id`, `resource_type`, `resource_id`) rather than a direct foreign key, allowing flexible user-or-group ownership.

---

## Feature Module System

`papermerge/core/router_loader.py` auto-discovers all routers at startup:

```python
# router_loader.py — simplified
import importlib, pkgutil
from papermerge.core import features

def load_all_routers(app):
    for finder, name, _ in pkgutil.iter_modules(features.__path__):
        try:
            mod = importlib.import_module(f"papermerge.core.features.{name}.router")
            if hasattr(mod, "router"):
                app.include_router(mod.router, prefix=settings.api_prefix)
        except ModuleNotFoundError:
            pass  # feature has no router (ownership, page_mngm, special_folders)
```

Every feature module with a `router.py` containing a `router` attribute is automatically included. No registration step required.

### Feature Module Structure

```
features/my_feature/
├── __init__.py
├── router.py        # APIRouter with prefix="/my-feature"
├── schema.py        # Pydantic v2 models (request + response)
├── service.py       # Pure business logic functions
└── db/
    ├── __init__.py
    ├── orm.py       # SQLAlchemy ORM models
    └── api.py       # Async DB functions (no HTTP concerns)
```

---

## Adding a New Feature

### 1. Create the module skeleton

```bash
mkdir -p papermerge/core/features/my_feature/db
touch papermerge/core/features/my_feature/{__init__,router,schema,service}.py
touch papermerge/core/features/my_feature/db/{__init__,orm,api}.py
```

### 2. Define ORM models (`db/orm.py`)

```python
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, ForeignKey
from uuid import UUID
from papermerge.core.db.base import Base

class MyModel(Base):
    __tablename__ = "my_models"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
```

### 3. Define Pydantic schemas (`schema.py`)

```python
from pydantic import BaseModel, ConfigDict
from uuid import UUID

class MyModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str

class MyModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
```

### 4. Write business logic (`service.py`)

```python
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .db.orm import MyModel
from .schema import MyModelCreate, MyModelResponse

async def list_items(session: AsyncSession, tenant_id: UUID) -> list[MyModelResponse]:
    result = await session.execute(
        select(MyModel).where(MyModel.tenant_id == tenant_id)
    )
    return [MyModelResponse.model_validate(r) for r in result.scalars()]
```

### 5. Create the router (`router.py`)

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from papermerge.core.db.engine import get_session
from papermerge.core.auth import get_current_user
from papermerge.core.db.models import User
from . import service
from .schema import MyModelCreate, MyModelResponse

router = APIRouter(prefix="/my-feature", tags=["My Feature"])

@router.get("", response_model=list[MyModelResponse])
async def list_items(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MyModelResponse]:
    return await service.list_items(session, user.tenant_id)
```

### 6. Create a migration

```bash
alembic revision --autogenerate -m "add my_feature table"
alembic upgrade head
```

### 7. Write tests

```python
# tests/features/my_feature/test_my_feature.py
import os, uuid
from unittest.mock import MagicMock, AsyncMock
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from papermerge.core.features.my_feature.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_session

def _make_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    return u

def _make_db():
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    return db

app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_current_user] = lambda: _make_user()
app.dependency_overrides[get_session] = lambda: _make_db()
client = TestClient(app)

def test_list_items_empty():
    response = client.get("/my-feature")
    assert response.status_code == 200
    assert response.json() == []
```

The router is auto-discovered — no registration step needed.

---

## Authentication & Authorization

### JWT Flow

1. `POST /auth/login` with `username` + `password` (form data) returns `access_token` + `refresh_token`
2. All subsequent requests: `Authorization: Bearer <access_token>`
3. `POST /auth/refresh` with `refresh_token` returns a new `access_token`
4. `POST /auth/logout` invalidates the current token (stored in Redis blocklist)

### Scopes

Permission scopes are string constants defined in `papermerge/core/auth/scopes.py`. Each scope follows the pattern `resource:action` (e.g., `node:view`, `user:create`, `tenant:admin`).

Scopes are assigned to roles. Users belong to groups; groups have roles. The JWT encodes the union of all scopes from all roles across all groups the user belongs to.

To protect an endpoint:

```python
from fastapi import Security
from papermerge.core.auth import get_current_user, scopes

@router.delete("/{item_id}")
async def delete_item(
    item_id: UUID,
    user: Annotated[User, Security(get_current_user, scopes=[scopes.MY_FEATURE_DELETE])],
    ...
):
    ...
```

### ABAC Policy Engine

For attribute-based access control beyond scopes, use the policy engine (`papermerge/core/features/policies/engine.py`):

```python
from papermerge.core.features.policies.engine import PolicyEngine, PolicyContext

engine = PolicyEngine(db_adapter=db)
ctx = PolicyContext(
    user_id=str(user.id),
    tenant_id=str(user.tenant_id),
    resource_type="document",
    resource_id=str(document_id),
    action="delete",
)
decision = await engine.evaluate(ctx)
if not decision.allowed:
    raise HTTPException(403, detail=decision.reason)
```

---

## Database Layer

### Session Management

```python
from papermerge.core.db.engine import get_session, AsyncSession

# In router handler
async def my_handler(session: Annotated[AsyncSession, Depends(get_session)]):
    result = await session.execute(select(MyModel).where(...))
    items = result.scalars().all()
    ...
```

The session is auto-committed at the end of the request if no exception is raised. Use `session.rollback()` explicitly on expected errors if needed.

### Migrations

```bash
# Generate migration from ORM changes
alembic revision --autogenerate -m "description"

# Apply
alembic upgrade head

# Rollback one step
alembic downgrade -1

# Current state
alembic current
```

Migration files are in `alembic/versions/`. Always review auto-generated migrations before applying — autogenerate can miss some index types and custom column defaults.

### Common Query Patterns

```python
# List with tenant filter
stmt = select(MyModel).where(MyModel.tenant_id == user.tenant_id).limit(limit)
result = await session.execute(stmt)
items = result.scalars().all()

# Get or 404
stmt = select(MyModel).where(MyModel.id == item_id, MyModel.tenant_id == user.tenant_id)
result = await session.execute(stmt)
item = result.scalar_one_or_none()
if not item:
    raise HTTPException(404)

# Count
stmt = select(func.count()).select_from(MyModel).where(...)
count = await session.scalar(stmt)

# Upsert (PostgreSQL)
from sqlalchemy.dialects.postgresql import insert
stmt = insert(MyModel).values(...).on_conflict_do_update(...)
await session.execute(stmt)
```

---

## Background Tasks & Celery

Celery workers handle OCR, email sync, file processing, and user deletion. The broker and result backend are both Redis.

### Dispatch a Task

```python
from papermerge.core import tasks, constants

# Fire-and-forget
tasks.send_task(
    constants.WORKER_OCR_DOCUMENT,
    kwargs={"document_id": str(doc_id), "lang": "eng"},
    route_name="ocr",
)
```

Task name constants are in `papermerge/core/constants.py`. Never hardcode task names.

### Define a New Task

```python
# papermerge/core/features/my_feature/tasks.py
from papermerge.core.celery_app import celery_app

@celery_app.task(name="my_feature.process_item", bind=True, max_retries=3)
def process_item(self, item_id: str):
    import asyncio
    asyncio.run(_process(item_id))

async def _process(item_id: str):
    async with AsyncSessionLocal() as session:
        ...
```

Register it in `constants.py`:
```python
MY_FEATURE_PROCESS = "my_feature.process_item"
```

---

## Workflow Engine (Prefect)

Multi-step approval workflows are built on Prefect 3.x. Workflow definitions live in the `workflows` feature module.

### Workflow Lifecycle

1. Define a workflow via `POST /workflows/` — stores definition + step config in DB
2. Start an instance via `POST /workflows/{id}/start` — creates a `WorkflowInstance` and dispatches to Prefect
3. Prefect flow runs, creating `WorkflowApprovalRequest` records for each step
4. Assignees see pending tasks at `GET /workflows/tasks/assigned`
5. Actions (approve/reject/comment) submitted via `POST /workflows/instances/{id}/actions`
6. Prefect resumes the flow after each action

### SLA Monitoring

Each workflow step can have an SLA config. A scheduled Celery task checks deadlines and creates `WorkflowSLAAlert` records. The compliance dashboard at `GET /workflows/sla/dashboard` aggregates on-track / warning / breached counts.

---

## Storage Layer

The storage abstraction in `papermerge/storage/` supports three backends:

| Backend | Config | Use Case |
|---|---|---|
| `local` | `PM_STORAGE__LOCAL__PATH` | Development, single-node |
| `s3` | `PM_STORAGE__S3__*` | AWS S3, Cloudflare R2, Linode |
| `minio` | `PM_STORAGE__S3__ENDPOINT_URL` | Self-hosted S3-compatible |

All backends implement `get_storage_backend()` → a common interface with `upload()`, `download()`, `delete()`, `sign_url()`.

```python
from papermerge.storage.base import get_storage_backend

storage = get_storage_backend()
await storage.upload(path="tenant_id/doc_id/v1/file.pdf", data=file_bytes)
url = await storage.sign_url("tenant_id/doc_id/v1/file.pdf", expires=3600)
```

---

## Testing

### Test Pattern

All feature tests use a minimal FastAPI app with the router under test, mocked DB session, and overridden auth dependency:

```python
os.environ.setdefault("PM_DB_URL", "postgresql+asyncpg://x:x@localhost/x")
# ^ Must be set before any papermerge import that touches settings

from fastapi.testclient import TestClient
from fastapi import FastAPI
from papermerge.core.features.my_feature.router import router
from papermerge.core.features.auth import get_current_user
from papermerge.core.db.engine import get_session

app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_current_user] = lambda: mock_user
app.dependency_overrides[get_session] = lambda: mock_db
client = TestClient(app)
```

### Mocking the DB Session

```python
from unittest.mock import AsyncMock, MagicMock

def _make_db():
    db = AsyncMock()
    # For queries that return a result set
    result = MagicMock()
    result.scalars.return_value.all.return_value = []   # list queries
    result.scalar_one_or_none.return_value = None       # get-by-id queries
    result.scalar.return_value = 0                      # count queries
    db.execute.return_value = result
    return db
```

### Running Tests

```bash
# All tests
.venv/bin/pytest tests/ -q

# Single feature
.venv/bin/pytest tests/features/workflows/ -v

# With output (useful for debugging)
.venv/bin/pytest tests/features/policies/ -s

# Fast: only changed files (requires pytest-testmon)
.venv/bin/pytest tests/ --testmon
```

### Coverage

```bash
.venv/bin/pytest tests/ --cov=papermerge/core/features --cov-report=html
open htmlcov/index.html
```

---

## Code Conventions

### Python Style

- Tabs for indentation (not spaces)
- Modern union syntax: `str | None`, `list[str]`, `dict[str, Any]`
- Async throughout — no `def` in handlers, always `async def`
- Pydantic v2: `model_config = ConfigDict(extra='forbid')`, `model_validate()` not `from_orm()`

### IDs

All IDs are UUID7 strings. Generate with:

```python
from uuid6 import uuid7
id: str = str(uuid7())
```

Or as a Pydantic field default:
```python
from uuid6 import uuid7
id: str = Field(default_factory=lambda: str(uuid7()))
```

### Logging

Use module-level loggers:

```python
import logging
logger = logging.getLogger(__name__)

# Log helpers that format paths/IDs cleanly
def _log_pretty_path(path: Path) -> str:
    return str(path.relative_to(BASE_PATH))
```

### Error Handling

Validate at router boundaries, not deep in service functions. Services should raise domain exceptions; routers catch and convert to HTTP:

```python
# service.py
class ItemNotFound(Exception):
    pass

# router.py
try:
    item = await service.get_item(...)
except service.ItemNotFound:
    raise HTTPException(status_code=404, detail="Item not found")
```

---

## Deployment

### Docker Compose (Production)

```yaml
services:
  api:
    image: ghcr.io/nyimbi/darchiva:latest
    environment:
      PM_DB_URL: postgresql+asyncpg://postgres:${DB_PASSWORD}@db/darchiva
      PM_SECURITY__SECRET_KEY: ${SECRET_KEY}
      PM_REDIS_URL: redis://redis:6379/0
      PM_STORAGE__TYPE: s3
      PM_STORAGE__S3__BUCKET: ${S3_BUCKET}
    depends_on: [db, redis]
    ports: ["8000:8000"]

  worker:
    image: ghcr.io/nyimbi/darchiva:latest
    command: celery -A config worker -c 4 --loglevel=info
    environment: *api-env
    depends_on: [db, redis]

  db:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: darchiva
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: [pgdata:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes: [redisdata:/data]
```

### Health Checks

- Liveness: `GET /probe/liveness` — checks DB with `SELECT 1`
- Readiness: `GET /monitoring/health` — checks DB + Redis
- Metrics: `GET /monitoring/metrics` — Prometheus format

### Kubernetes

Mount secrets as environment variables. Configure readiness probe on `/monitoring/health` and liveness on `/probe/liveness`. Run migrations as an init container:

```yaml
initContainers:
  - name: migrate
    image: ghcr.io/nyimbi/darchiva:latest
    command: ["alembic", "upgrade", "head"]
    env: *env-vars
```

### Scaling

- API: stateless, scale horizontally; sticky sessions not required
- Workers: scale by queue — `ocr` queue separately from `default`
- DB: read replicas not supported by default (all queries use primary)
- Redis: single-instance or Sentinel; Cluster not tested

---

## Scan Agent Fleet Management

### Overview

Scan agents are lightweight Python processes that run on scan stations (Raspberry Pi, desktop PCs, or any Linux host). Each agent:

1. Registers itself with the central server via `POST /scan-agents/register` using a provisioning key
2. Receives an API key back; all subsequent calls use `Authorization: Bearer <api_key>`
3. Polls for scanning jobs, captures pages via eSCL/TWAIN/camera, runs OpenCV quality check, hashes each page with BLAKE3, and uploads to the server

### Agent Registration API

```
POST /scan-agents/register
  { "station_name": "station-01", "provisioning_key": "..." }
  → { "agent_id": "...", "api_key": "sk-agent-..." }

GET  /scan-agents/              # list all registered agents
GET  /scan-agents/{id}/status   # health and last-seen
POST /scan-agents/{id}/config   # push config to agent
DELETE /scan-agents/{id}        # deregister
```

### Quality Pipeline

```
Raw JPEG from scanner
    │
    ▼ OpenCV QualityAssessor (primary — always runs)
    │   blur detection (Laplacian variance)
    │   brightness + contrast checks
    │   skew angle estimation
    │   noise level estimation
    │
    ├── PASS → create QualityAssessment record (status=passed)
    │          queue process_upload → OCR → embed → NER
    │
    └── FAIL → create QualityAssessment (status=failed)
               queue darchiva.scanning.rescan_requested
               (operator notified, page re-scanned)

Optional second pass (VLM, only if enabled):
    └── Qwen2.5-VL via local LiteLLM proxy
        Prompt: "Rate scan quality 1-10 with issues"
        Result appended to QualityAssessment.vlm_feedback
```

### BLAKE3 Content Deduplication

Every scanned page is hashed with BLAKE3 before upload. The hash is stored in `ScanProvenance.blake3_hash`. If an identical hash already exists for the same tenant, the page is skipped — no duplicate stored.

```python
from blake3 import blake3
page_hash = blake3(page_bytes).hexdigest()
```

### Adding a New Scanner Protocol

1. Create `papermerge/core/scanner/<protocol>.py` inheriting from `scanner/base.py::Scanner`
2. Implement `scan(options: ScanOptions) -> ScanResult`
3. Register it in `papermerge/core/features/scanners/service.py::ScannerService._get_driver()`

---

## Document Intelligence Pipeline

After a document upload completes (`process_upload` Celery task finishes), two downstream tasks are queued:

### Semantic Embeddings

Task: `darchiva.documents.index_embeddings`

```python
# Fetches latest DocumentVersion.text (from OCR)
# Calls SemanticSearch.index_document(document_id, version_id, text)
# Uses Ollama nomic-embed-text via embedding_base_url setting
# Stores vectors in pgvector
```

Enable semantic search: `PM_SEMANTIC_SEARCH_ENABLED=true`

Query endpoint: `GET /search/semantic?q=<query>&limit=<n>`

### Named Entity Recognition

Task: `darchiva.documents.extract_entities`

```python
# Calls LiteLLM proxy (qwen2.5-VL) with OCR text
# Extracts: persons, organizations, dates, amounts, locations
# Stores in Document.document_metadata (JSONB)
# Uses PM_LITELLM_NER_MODEL (default: qwen2.5-VL)
```

The extracted entities appear in `GET /nodes/{id}` response under `document_metadata.entities`.

---

## Legal Holds & Retention

### Endpoints

```
PUT    /legal-holds/{document_id}           # place hold
DELETE /legal-holds/{document_id}           # release hold
GET    /legal-holds/{document_id}           # hold status
PUT    /legal-holds/{document_id}/retention # set retention date/policy
POST   /legal-holds/expire                  # auto-expire past-date holds
```

### ORM Fields (Document model)

```python
legal_hold: bool           # True = document cannot be deleted
retention_date: datetime   # Auto-expires hold on this date
retention_policy: str      # e.g. "7yr-financial", "3yr-hr"
document_metadata: dict    # JSONB — entities, custom fields, tags
```

### Enforcement

Deletion endpoints check `legal_hold` before proceeding. If `True`, a 409 is returned. The `POST /legal-holds/expire` endpoint (designed for a nightly cron) releases holds where `retention_date < now()`.

---

## Form Recognition Pipeline

1. Operator submits document for extraction: `POST /forms/extractions`
2. Celery task `darchiva.form.process` runs:
   - Calls `FormRecognitionService.recognize_and_extract(document_id, tenant_id, page_images, ocr_results)`
   - Service identifies template from `DocumentType` tag, extracts field values, detects signatures
   - Stores in `FormExtraction` + `ExtractedField` ORM records
3. Result is queryable at `GET /forms/extractions/{id}`
4. If `confidence < 0.75`, status is set to `needs_review` → appears in review queue
5. Operator reviews in UI, corrects low-confidence fields, confirms → `POST /forms/extractions/{id}/confirm`
6. Confirmed fields written back to `Document.document_metadata`

---

## Frontend Architecture

See [frontend-guide.md](frontend-guide.md) for the complete React developer guide. Key integration points from the backend perspective:

### Thumbnail Endpoints

```
GET /thumbnails/{document_id}              → first-page JPEG (auth required)
GET /thumbnails/{document_id}/page/{n}    → page N JPEG (generated on demand)
GET /thumbnails/{document_id}/full        → full document file (inline)
```

These are served by `router_thumbnails.py` and require `NODE_VIEW` scope. Preview generation is synchronous on first request; subsequent requests return the cached JPEG.

### Celery Task Routes

| Task name | Queue |
|---|---|
| `process_upload` | `s3` (or `PM_S3_QUEUE_NAME`) |
| `s3preview` | `s3preview` (or `PM_S3_PREVIEW_QUEUE_NAME`) |
| `ocr` | `ocr` |
| `darchiva.documents.index_embeddings` | `core` |
| `darchiva.documents.extract_entities` | `core` |
| `darchiva.scanning.rescan_requested` | `core` |
| `darchiva.form.process` | `core` |
| `darchiva.ingestion.*` | `core` |
| `darchiva.email.*` | `core` |

Run separate worker processes per queue for isolation:

```bash
celery -A config worker -Q core -c 4 --loglevel=info
celery -A config worker -Q ocr -c 2 --loglevel=info
celery -A config worker -Q s3,s3preview -c 4 --loglevel=info
```
