# dArchiva — Enterprise Document Intelligence Platform

dArchiva is a production-grade, multi-tenant document management and intelligence platform built on [papermerge-core](https://github.com/papermerge/papermerge-core). It extends the open-source DMS foundation with enterprise capabilities: ABAC policy enforcement, workflow automation, physical inventory management, AI-powered form extraction, document quality assessment, and a 42-feature REST API surface.

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────────┐
│                          Clients                                │
│            React UI  ·  REST API  ·  CLI (pm)                   │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS
┌────────────────────────────▼────────────────────────────────────┐
│                    FastAPI Application                          │
│   42 auto-discovered routers · JWT auth · Scope-based RBAC      │
│   ABAC policy engine · Per-tenant isolation                     │
└────────┬──────────────────┬─────────────────────────────────────┘
         │                  │
┌────────▼──────┐  ┌────────▼──────┐  ┌─────────────────────────┐
│  PostgreSQL   │  │  Celery/Redis │  │  Object Storage         │
│  + pgvector   │  │  OCR Workers  │  │  (S3 / MinIO / R2)      │
└───────────────┘  └───────────────┘  └─────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │   Prefect Workflows │
              └─────────────────────┘
```

## Features

### Core Document Management
- **Hierarchical folders** — desktop-style tree with drag-and-drop
- **Document versioning** — full version history with diff support
- **OCR** — Tesseract, Qwen-VL (Ollama), or auto-select
- **Full-text search** — pgvector-backed with custom field filtering
- **Page management** — reorder, rotate, extract, merge pages
- **Tags and metadata** — colored tags + typed custom fields per document type

### Intelligence & Automation
- **AI Form Recognition** — structured data extraction from known form templates
- **Document Segmentation** — auto-detect multiple documents in a single scan
- **Quality Assessment** — rule-based + VLM-powered scan quality scoring
- **Automated Routing** — condition-based document routing rules
- **Serial Numbers** — configurable pattern sequences auto-assigned on upload
- **OCR Proxy** — server-side proxy for Ollama, OpenAI, Anthropic, Azure OpenAI

### Workflow & Compliance
- **Workflow Engine** — Prefect-backed multi-step approval workflows with SLA monitoring
- **ABAC Policy Engine** — attribute-based access control with DSL, dry-run, and audit logging
- **Provenance & Chain-of-Custody** — SHA-512 hash-chained immutable event records
- **Audit Logging** — full audit trail with anomaly detection and compliance reports
- **Encryption** — tenant-level key management with rotation and single-view tokens

### Multi-Tenant Enterprise
- **Multi-tenancy** — complete tenant isolation at data and storage layers
- **RBAC** — roles with scoped permissions; groups with shared ownership
- **Departments** — hierarchical org structure with access rule inheritance
- **Billing** — usage tracking, invoice management, cost estimation
- **Tenant Provisioning** — one-shot tenant setup (storage + AI + subscription + admin)

### Scanning & Physical Records
- **Scanner Management** — network scanner discovery, registration, API key auth
- **Scan Batches** — full lifecycle with operator assignment and review queue
- **Scanning Projects** — enterprise-scale digitization project management with SLAs, costing, QC
- **Physical Inventory** — warehouse locations, containers, QR/DataMatrix codes, chain-of-custody

### Integration
- **Email Ingestion** — IMAP, Microsoft Graph, Gmail with routing rules
- **API Tokens** — scoped personal access tokens with expiry
- **Prometheus Metrics** — `/monitoring/metrics` endpoint for scraping

## Quick Start

### With Docker Compose

```bash
git clone https://github.com/nyimbi/papermerge-core.git
cd papermerge-core
docker compose up
```

The API will be available at `http://localhost:8000`. OpenAPI docs at `http://localhost:8000/docs`.

### Local Development

```bash
# Requires Python 3.13+, PostgreSQL 17+pgvector, Redis
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[quality,scanner]"

# Configure
export PM_DB_URL="postgresql+asyncpg://user:pass@localhost/darchiva"
export PM_SECURITY__SECRET_KEY="your-secret-key"

# Migrate
alembic upgrade head

# Run
fastapi dev papermerge/app.py
```

See [docs/developer-guide.md](docs/developer-guide.md) for the full setup guide.

## API

The platform auto-discovers all 42 feature routers at startup. Base URL is configurable via `PM_API_PREFIX` (default: root `/`).

Interactive API documentation: `GET /docs` (Swagger UI) or `GET /redoc` (ReDoc).

Authentication: `POST /auth/login` → JWT bearer token. All protected endpoints require `Authorization: Bearer <token>`.

See [docs/features.md](docs/features.md) for the complete feature and endpoint reference.

## Configuration

All configuration is via environment variables (pydantic-settings, `__` as nested separator):

| Variable | Default | Description |
|---|---|---|
| `PM_DB_URL` | required | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `PM_SECURITY__SECRET_KEY` | required | JWT signing key |
| `PM_SECURITY__TOKEN_EXPIRE_MINUTES` | `60` | JWT expiry |
| `PM_REDIS_URL` | `redis://localhost:6379/0` | Redis URL for Celery |
| `PM_STORAGE__TYPE` | `local` | Storage backend: `local`, `s3`, `minio` |
| `PM_STORAGE__S3__BUCKET` | — | S3 bucket name |
| `PM_API_PREFIX` | `` | URL prefix for all routes |

## Testing

```bash
# Run all tests
.venv/bin/pytest tests/ -q

# Single feature
.venv/bin/pytest tests/features/workflows/ -v

# Type checking
uv run pyright
```

Current status: **80 passing, 2 skipped**.

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115+ with async SQLAlchemy |
| Database | PostgreSQL 17 + pgvector |
| Task Queue | Celery + Redis |
| Workflow Engine | Prefect 3.x |
| Storage | S3-compatible (MinIO, R2, Linode) |
| OCR | ocrmypdf (Tesseract) + Ollama (Qwen-VL) |
| Auth | JWT (python-jose) + OAuth2 password flow |
| Models | Pydantic v2 |
| Migrations | Alembic |

## Documentation

- [Developer Guide](docs/developer-guide.md) — architecture, setup, adding features, testing
- [Features Reference](docs/features.md) — all 42 features with endpoint listings
- [Changelog](changelog.md)

## CLI

`pm` — management CLI for search index, migrations, and diagnostics.

```bash
pm --help
pm search build      # rebuild search index
pm search stats      # search index statistics
```

## License

Apache-2.0 — see [LICENSE](LICENSE).
