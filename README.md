# dArchiva — Enterprise Document Intelligence Platform

dArchiva is a production-grade, multi-tenant document management and intelligence platform built on [papermerge-core](https://github.com/papermerge/papermerge-core). It extends the open-source DMS foundation with enterprise capabilities: distributed scan agent fleet management, ABAC policy enforcement, workflow automation, AI-powered form extraction, document quality assessment, legal holds, content deduplication, and a 50+ feature REST API surface.

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────────────────────┐
│                              Clients                                 │
│         React UI  ·  REST API  ·  CLI (pm)  ·  Scan Agents          │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ HTTPS
┌────────────────────────────▼─────────────────────────────────────────┐
│                       FastAPI Application                            │
│   50+ auto-discovered routers · JWT auth · Scope-based RBAC          │
│   ABAC policy engine · Per-tenant isolation · pgvector search        │
└────────┬──────────────────┬────────────────────────┬─────────────────┘
         │                  │                        │
┌────────▼──────┐  ┌────────▼──────┐  ┌─────────────▼───────────────┐
│  PostgreSQL   │  │  Celery/Redis │  │  Object Storage             │
│  + pgvector   │  │  OCR · NER    │  │  (S3 / MinIO / R2)          │
│  + JSONB meta │  │  Embeddings   │  └─────────────────────────────┘
└───────────────┘  └───────────────┘
         │                  │
┌────────▼──────────────────▼──────────────────────────────────────────┐
│   Scan Agent Fleet (eSCL · TWAIN · Camera)                          │
│   Per-station: OpenCV QC → BLAKE3 hash → JPEG upload → OCR queue    │
└──────────────────────────────────────────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │   Prefect Workflows │
              └─────────────────────┘
```

## Features

### Core Document Management
- **Hierarchical folders** — desktop-style tree with drag-and-drop
- **Document versioning** — full version history with diff support
- **OCR** — Tesseract via ocrmypdf; Qwen2.5-VL via local LiteLLM proxy; auto-select
- **Full-text search** — meilisearch + pgvector for semantic search
- **Page management** — reorder, rotate, extract, merge pages
- **Tags and metadata** — colored tags + typed custom fields per document type
- **Content deduplication** — BLAKE3 hash on every scanned page; exact-duplicate skipped on ingest

### Intelligence & Automation
- **AI Form Recognition** — structured data extraction from known form templates via Qwen2.5-VL
- **Named Entity Recognition** — automatic extraction of persons, orgs, dates, amounts from OCR text
- **Semantic Search** — pgvector embeddings (Ollama nomic-embed-text); `GET /search/semantic`
- **Document Segmentation** — auto-detect multiple documents in a single scan
- **Quality Assessment** — OpenCV primary pipeline (blur, brightness, skew, noise); Qwen2.5-VL optional deep analysis
- **Automated Routing** — condition-based document routing rules (document type, tag, filename, metadata)
- **Serial Numbers** — configurable pattern sequences auto-assigned on upload
- **OCR Proxy** — server-side proxy for Ollama, OpenAI, Anthropic, Azure OpenAI

### Scanning & Physical Records
- **Scan Agent Fleet** — distributed scan stations (Raspberry Pi or any Linux host) with eSCL, TWAIN, or camera capture; registered via API key; config pushed from central server
- **Fleet Management UI** — register/deregister agents, push config, view health and status per station
- **Scanner Management** — network scanner discovery, registration, eSCL protocol support
- **Scan Batches** — full lifecycle with operator assignment, quality check, and review queue
- **Scanning Projects** — enterprise-scale digitization project management with SLAs, milestones, costing, and QC pass/fail thresholds
- **Camera Capture** — high-resolution desk-mounted camera support; multi-frame stitching for oversized documents
- **Physical Inventory** — warehouse locations, containers, QR/DataMatrix codes, chain-of-custody

### Workflow & Compliance
- **Workflow Engine** — Prefect-backed multi-step approval workflows with SLA monitoring
- **Legal Holds** — place/release holds on documents; retention date and policy enforcement; auto-expiry
- **ABAC Policy Engine** — attribute-based access control with DSL, dry-run, and audit logging
- **Provenance & Chain-of-Custody** — SHA-512 hash-chained immutable event records
- **Audit Logging** — full audit trail with anomaly detection and compliance reports
- **Encryption** — tenant-level key management with rotation and single-view tokens

### Case & Portfolio Management
- **Cases** — logical groupings of documents with status lifecycle (open → closed)
- **Bundles** — ordered document sets within a case; reorder and lock support
- **Portfolios** — top-level container grouping multiple cases
- **Access Control** — per-case permission grants (viewer / editor / manager)

### Multi-Tenant Enterprise
- **Multi-tenancy** — complete tenant isolation at data and storage layers
- **RBAC** — roles with scoped permissions; groups with shared ownership
- **Departments** — hierarchical org structure with access rule inheritance
- **Billing** — usage tracking, invoice management, cost estimation
- **Tenant Provisioning** — one-shot tenant setup (storage + AI + subscription + admin)

### Integration
- **Email Ingestion** — IMAP, Microsoft Graph, Gmail with routing rules
- **Ingestion Sources** — folder watch, email, scanner, API push, cloud storage
- **API Tokens** — scoped personal access tokens with expiry
- **Prometheus Metrics** — `/monitoring/metrics` endpoint for scraping

---

## Quick Start

### With Docker Compose

```bash
git clone https://github.com/nyimbi/papermerge-core.git
cd papermerge-core
docker compose up
```

API: `http://localhost:8000` · Swagger UI: `http://localhost:8000/docs`

Frontend (dev):
```bash
cd darchiva-ui
npm install
npm run dev    # http://localhost:5173
```

### Local Development

```bash
# Requires Python 3.13+, PostgreSQL 17+pgvector, Redis
python3.14 -m venv .venv && source .venv/bin/activate
pip install -e ".[quality,scanner]"

export PM_DB_URL="postgresql+asyncpg://user:pass@localhost/darchiva"
export PM_SECURITY__SECRET_KEY="$(openssl rand -hex 32)"
export PM_LITELLM_BASE_URL="http://localhost:4000/v1"      # local LiteLLM
export PM_LITELLM_API_KEY="sk-..."

alembic upgrade head
fastapi dev papermerge/app.py
```

See [docs/developer-guide.md](docs/developer-guide.md) for the full setup guide, including scan agent deployment.

---

## API

The platform auto-discovers all routers at startup. Base URL configurable via `PM_API_PREFIX` (default: root `/`).

Interactive docs: `GET /docs` (Swagger UI) · `GET /redoc` (ReDoc)

Auth: `POST /auth/login` → JWT bearer. All protected endpoints require `Authorization: Bearer <token>`.

### Key Endpoint Groups

| Prefix | Description |
|---|---|
| `/nodes/` | Documents and folders (CRUD, move, page management) |
| `/thumbnails/` | JPEG thumbnails — `/{doc_id}` (first page), `/{doc_id}/page/{n}` |
| `/scanners/` | Scanner registration, jobs, batches |
| `/scanning-projects/` | Project management, milestones, QC |
| `/scan-agents/` | Fleet management — register, config push, status |
| `/cases/` | Case lifecycle + bundle management |
| `/portfolios/` | Portfolio CRUD |
| `/forms/` | Form extraction queue + template management |
| `/routing/rules` | Routing rule CRUD + test endpoint |
| `/ingestion/` | Ingestion source + job management |
| `/search/` | Full-text + semantic search |
| `/legal-holds/` | Hold placement, retention policy |
| `/monitoring/` | Health, metrics, audit |

---

## Configuration

All configuration via environment variables (pydantic-settings, `__` as nested separator).

### Required

| Variable | Description |
|---|---|
| `PM_DB_URL` | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `PM_SECURITY__SECRET_KEY` | JWT signing key (min 32 chars) |

### Commonly Set

| Variable | Default | Description |
|---|---|---|
| `PM_REDIS_URL` | `redis://localhost:6379/0` | Celery broker |
| `PM_STORAGE__TYPE` | `local` | `local`, `s3`, or `minio` |
| `PM_STORAGE__S3__BUCKET` | — | S3 bucket name |
| `PM_API_PREFIX` | `` | URL prefix for all routes |
| `PM_LITELLM_BASE_URL` | `http://localhost:4000/v1` | LiteLLM proxy base URL |
| `PM_LITELLM_API_KEY` | — | LiteLLM API key |
| `PM_LITELLM_NER_MODEL` | `qwen2.5-VL` | Model for NER extraction |
| `PM_EMBEDDING_BASE_URL` | `http://localhost:11434` | Ollama embedding server |

### Optional / Advanced

| Variable | Default | Description |
|---|---|---|
| `PM_SEMANTIC_SEARCH_ENABLED` | `false` | Enable `/search/semantic` endpoint |
| `PM_PREFIX` | — | Celery queue name prefix (multi-cluster) |
| `PM_S3_QUEUE_NAME` | — | Override S3 worker queue name |
| `PM_S3_PREVIEW_QUEUE_NAME` | — | Override preview worker queue name |
| `PM_SECURITY__TOKEN_EXPIRE_MINUTES` | `60` | JWT expiry |

---

## Testing

```bash
uv run pytest tests/ci -q          # CI test suite (no mocks — real DB)
uv run pytest tests/ -v            # all tests
uv run pytest tests/features/workflows/ -v  # single feature
uv run pyright                      # type checking
```

Current status: **80 passing, 2 skipped**.

---

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115+ · async SQLAlchemy · Pydantic v2 |
| Database | PostgreSQL 17 + pgvector + JSONB |
| Task Queue | Celery + Redis |
| Workflow Engine | Prefect 3.x |
| Storage | S3-compatible (MinIO, R2, Linode) |
| OCR | ocrmypdf (Tesseract) + Qwen2.5-VL (local LiteLLM) |
| Auth | JWT (python-jose) + OAuth2 password flow |
| Migrations | Alembic |
| Quality | OpenCV + optional Qwen2.5-VL (VLM secondary pass) |
| Hashing | BLAKE3 (content dedup per scanned page) |
| Embeddings | nomic-embed-text via Ollama |
| Frontend | React 18 · Vite · TanStack Query · shadcn/ui |

---

## Documentation

- [Developer Guide](docs/developer-guide.md) — architecture, setup, adding features, scan agents, testing
- [Frontend Guide](docs/frontend-guide.md) — React app architecture, adding features, modal system
- [Features Reference](docs/features.md) — endpoint reference per feature module
- [Scan Agent API](docs/scan-agent-api.yaml) — OpenAPI spec for the agent registration protocol
- [Changelog](changelog.md)

---

## CLI

```bash
pm --help
pm search build      # rebuild search index
pm search stats      # search index statistics
pm migrate           # run alembic upgrade head
```

---

## License

Apache-2.0 — see [LICENSE](LICENSE).
