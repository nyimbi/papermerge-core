# dArchiva Feature Reference

This document describes all 42 features exposed by the dArchiva platform. Features correspond to auto-discovered router modules under `papermerge/core/features/`.

Each feature section includes: purpose, key capabilities, and a full endpoint listing with HTTP method, path, required scope (if any), and description.

---

## Table of Contents

1. [API Tokens](#1-api-tokens)
2. [Audit Logging](#2-audit-logging)
3. [Authentication](#3-authentication)
4. [Scan Batches](#4-scan-batches)
5. [Billing](#5-billing)
6. [Bundles](#6-bundles)
7. [Cases](#7-cases)
8. [Custom Fields](#8-custom-fields)
9. [Dashboard](#9-dashboard)
10. [Departments](#10-departments)
11. [Documents](#11-documents)
12. [Document Types](#12-document-types)
13. [Email Ingestion](#13-email-ingestion)
14. [Encryption](#14-encryption)
15. [Form Recognition](#15-form-recognition)
16. [Groups](#16-groups)
17. [Ingestion Pipelines](#17-ingestion-pipelines)
18. [Physical Inventory](#18-physical-inventory)
19. [Liveness Probe](#19-liveness-probe)
20. [Monitoring](#20-monitoring)
21. [Nodes (File Tree)](#21-nodes-file-tree)
22. [OCR Proxy](#22-ocr-proxy)
23. [Permissions](#23-permissions)
24. [ABAC Policies](#24-abac-policies)
25. [Portfolios](#25-portfolios)
26. [Preferences](#26-preferences)
27. [Provenance & Chain-of-Custody](#27-provenance--chain-of-custody)
28. [Document Quality](#28-document-quality)
29. [Roles](#29-roles)
30. [Routing Rules](#30-routing-rules)
31. [Scanners](#31-scanners)
32. [Scanning Projects](#32-scanning-projects)
33. [Search](#33-search)
34. [Segmentation](#34-segmentation)
35. [Serial Numbers](#35-serial-numbers)
36. [Shared Nodes](#36-shared-nodes)
37. [Tags](#37-tags)
38. [OCR Tasks](#38-ocr-tasks)
39. [Tenants](#39-tenants)
40. [User Home](#40-user-home)
41. [Users](#41-users)
42. [Workflows](#42-workflows)

---

## 1. API Tokens

**Module:** `api_tokens` | **Prefix:** `/tokens`

Personal Access Tokens (PATs) for programmatic API access. Tokens carry a scoped subset of the creating user's permissions and support optional expiry dates. Used for CI/CD integrations, scripts, and third-party connectors.

| Method | Path | Scope | Description |
|---|---|---|---|
| `GET` | `/tokens` | — | List all tokens for current user |
| `POST` | `/tokens` | — | Create a new PAT |
| `GET` | `/tokens/{token_id}` | — | Get token details |
| `DELETE` | `/tokens/{token_id}` | — | Revoke a token |

---

## 2. Audit Logging

**Module:** `audit` | **Prefix:** `/audit-logs`

Immutable audit trail of all platform operations. Every create/update/delete operation on a tracked resource is logged with actor, timestamp, operation type, and affected table. Analytics endpoints expose trends, top users, and automated security anomaly detection. Compliance reports can be generated for auditor delivery.

| Method | Path | Scope | Description |
|---|---|---|---|
| `GET` | `/audit-logs/` | `audit_log:view` | Paginated audit log (filterable by user, operation, table) |
| `GET` | `/audit-logs/{audit_log_id}` | `audit_log:view` | Get single audit entry |
| `GET` | `/audit-logs/analytics/trend` | `audit_log:view` | Activity over time (hourly/daily/weekly) |
| `GET` | `/audit-logs/analytics/users/top` | `audit_log:view` | Top active users |
| `GET` | `/audit-logs/analytics/users/{user_id}` | `audit_log:view` | Activity summary for specific user |
| `GET` | `/audit-logs/analytics/operations` | `audit_log:view` | Operation type distribution |
| `GET` | `/audit-logs/analytics/security-alerts` | `audit_log:view` | Detected security anomalies |
| `GET` | `/audit-logs/analytics/compliance-report` | `audit_log:view` | Compliance audit report |

---

## 3. Authentication

**Module:** `auth` | **Prefix:** `/auth`

OAuth2 password flow with JWT access and refresh tokens. Supports token refresh, logout with server-side invalidation (Redis blocklist), and current-user profile retrieval.

| Method | Path | Scope | Description |
|---|---|---|---|
| `POST` | `/auth/login` | — | Username/password login; returns JWT tokens |
| `POST` | `/auth/refresh` | — | Refresh access token |
| `POST` | `/auth/logout` | — | Invalidate current token |
| `GET` | `/auth/me` | — | Current authenticated user profile |

---

## 4. Scan Batches

**Module:** `batches` | **Prefix:** `/batches`, `/locations`

Manages physical document scanning batches through a defined lifecycle: `created → in_progress → paused → completed → under_review → approved/rejected`. Supports operator assignment, bulk status updates, and metrics. Physical source locations (rooms, filing cabinets) are managed separately.

**Batch Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/batches` | List batches (filterable by status, assignee) |
| `POST` | `/batches` | Create a batch |
| `GET` | `/batches/stats` | Batch statistics |
| `GET` | `/batches/{batch_id}` | Get batch details |
| `PATCH` | `/batches/{batch_id}` | Update batch metadata |
| `DELETE` | `/batches/{batch_id}` | Delete a batch |
| `POST` | `/batches/{batch_id}/start` | Transition to in_progress |
| `POST` | `/batches/{batch_id}/pause` | Pause batch |
| `POST` | `/batches/{batch_id}/resume` | Resume paused batch |
| `POST` | `/batches/{batch_id}/complete` | Mark as completed |
| `POST` | `/batches/{batch_id}/submit-review` | Submit for review |
| `POST` | `/batches/{batch_id}/approve` | Approve batch |
| `POST` | `/batches/{batch_id}/reject` | Reject batch |
| `POST` | `/batches/{batch_id}/assign` | Assign to operator |
| `GET` | `/batches/{batch_id}/documents` | List batch documents |
| `POST` | `/batches/bulk-status` | Bulk update statuses |

**Location Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/locations` | List source locations |
| `POST` | `/locations` | Create location |
| `GET` | `/locations/{location_id}` | Get location |
| `PATCH` | `/locations/{location_id}` | Update location |
| `DELETE` | `/locations/{location_id}` | Delete location |

---

## 5. Billing

**Module:** `billing` | **Prefix:** `/billing`

Usage-based billing system with invoice lifecycle management. Tracks resource consumption per tenant, estimates costs for planned operations, manages billing alert thresholds, and handles the full invoice workflow from draft through payment. Invoices can be downloaded as PDFs.

| Method | Path | Description |
|---|---|---|
| `GET` | `/billing/dashboard` | Aggregated billing summary |
| `GET` | `/billing/usage/daily` | Daily usage breakdown |
| `POST` | `/billing/estimate` | Estimate cost for a set of operations |
| `GET` | `/billing/alerts` | List billing alerts |
| `POST` | `/billing/alerts` | Create billing alert |
| `PATCH` | `/billing/alerts/{alert_id}` | Update alert |
| `DELETE` | `/billing/alerts/{alert_id}` | Delete alert |
| `GET` | `/billing/invoices` | List invoices |
| `POST` | `/billing/invoices` | Create draft invoice |
| `GET` | `/billing/invoices/{invoice_id}` | Get invoice details |
| `PATCH` | `/billing/invoices/{invoice_id}` | Update invoice |
| `POST` | `/billing/invoices/{invoice_id}/send` | Send invoice to customer |
| `POST` | `/billing/invoices/{invoice_id}/pay` | Mark invoice as paid |
| `GET` | `/billing/invoices/{invoice_id}/pdf` | Download invoice PDF |

---

## 6. Bundles

**Module:** `bundles` | **Prefix:** `/bundles`

Named document collections organized into labelled sections. Bundles aggregate documents from anywhere in the tree into a logical output package. A generate endpoint produces a paginated PDF from all documents in the bundle, respecting section order.

| Method | Path | Description |
|---|---|---|
| `GET` | `/bundles` | List bundles |
| `POST` | `/bundles` | Create bundle |
| `GET` | `/bundles/{bundle_id}` | Bundle details |
| `PATCH` | `/bundles/{bundle_id}` | Update bundle |
| `DELETE` | `/bundles/{bundle_id}` | Delete bundle |
| `GET` | `/bundles/{bundle_id}/sections` | List sections |
| `POST` | `/bundles/{bundle_id}/sections` | Add section |
| `PATCH` | `/bundles/{bundle_id}/sections/{section_id}` | Update section |
| `DELETE` | `/bundles/{bundle_id}/sections/{section_id}` | Remove section |
| `POST` | `/bundles/{bundle_id}/sections/{section_id}/documents` | Add document to section |
| `DELETE` | `/bundles/{bundle_id}/sections/{section_id}/documents/{doc_id}` | Remove document |
| `POST` | `/bundles/{bundle_id}/generate` | Generate PDF output |

---

## 7. Cases

**Module:** `cases` | **Prefix:** `/cases`

Named document containers for legal or project work. Cases group related documents with access control. Can be nested inside portfolios for higher-level organization. Access grants specify which users or groups can view or modify a case.

| Method | Path | Description |
|---|---|---|
| `GET` | `/cases` | List cases |
| `POST` | `/cases` | Create case |
| `GET` | `/cases/{case_id}` | Case details |
| `PATCH` | `/cases/{case_id}` | Update case |
| `DELETE` | `/cases/{case_id}` | Delete case |
| `GET` | `/cases/{case_id}/documents` | List case documents |
| `POST` | `/cases/{case_id}/documents` | Associate document |
| `DELETE` | `/cases/{case_id}/documents/{doc_id}` | Remove association |
| `POST` | `/cases/{case_id}/access` | Grant access |
| `DELETE` | `/cases/{case_id}/access/{grant_id}` | Revoke access |

---

## 8. Custom Fields

**Module:** `custom_fields` | **Prefix:** `/custom-fields`

User-defined typed metadata fields (`text`, `date`, `number`, `boolean`, `select`) that attach to document types to form structured schemas. Fields can be owned by a user or a group. Select-type fields track option usage counts to prevent accidental deletion of in-use values.

| Method | Path | Description |
|---|---|---|
| `GET` | `/custom-fields` | List custom fields (paginated, filterable) |
| `POST` | `/custom-fields` | Create a custom field |
| `GET` | `/custom-fields/{field_id}` | Get field details |
| `PATCH` | `/custom-fields/{field_id}` | Update field |
| `DELETE` | `/custom-fields/{field_id}` | Delete field |
| `GET` | `/custom-fields/{field_id}/option-usage` | Get select option usage counts |

---

## 9. Dashboard

**Module:** `dashboard` | **Prefix:** `/dashboard`

Aggregated statistics for the authenticated user's home dashboard. All metrics are queried concurrently from the database. Storage bytes and OCR counts are real values computed from the `document_versions` and `ingestion_jobs` tables.

| Method | Path | Description |
|---|---|---|
| `GET` | `/dashboard/stats` | Total documents, monthly uploads, pending tasks, active workflows, storage bytes, OCR count |
| `GET` | `/dashboard/activity` | Recent activity feed from audit log (paginated) |

**Stats payload:**
```json
{
  "totalDocuments": 1842,
  "documentsThisMonth": 47,
  "pendingTasks": 3,
  "activeWorkflows": 2,
  "storageUsedBytes": 4831838208,
  "ocrProcessed": 1207
}
```

---

## 10. Departments

**Module:** `departments` | **Prefix:** `/departments`

Hierarchical organizational structure with parent-child department relationships. Access rules can be attached at the department level and inherited by subdepartments. Effective permission calculation considers the user's role within the department and any department-level grants.

| Method | Path | Description |
|---|---|---|
| `GET` | `/departments` | List top-level departments |
| `POST` | `/departments` | Create department |
| `GET` | `/departments/tree` | Full hierarchy tree |
| `GET` | `/departments/{dept_id}` | Department details |
| `PATCH` | `/departments/{dept_id}` | Update department |
| `DELETE` | `/departments/{dept_id}` | Delete department |
| `GET` | `/departments/{dept_id}/members` | List members |
| `POST` | `/departments/{dept_id}/members` | Add member |
| `DELETE` | `/departments/{dept_id}/members/{user_id}` | Remove member |
| `GET` | `/departments/{dept_id}/access-rules` | List access rules |
| `POST` | `/departments/{dept_id}/access-rules` | Add access rule |
| `DELETE` | `/departments/{dept_id}/access-rules/{rule_id}` | Delete rule |
| `GET` | `/departments/{dept_id}/effective-permissions` | Computed effective permissions |

---

## 11. Documents

**Module:** `document` | **Prefix:** `/documents`

Core document data plane. Handles document CRUD, file upload (binary or base64), scanned image ingestion, custom field value management per document, versioning, anomaly flagging, and thumbnail processing status tracking.

| Method | Path | Description |
|---|---|---|
| `GET` | `/documents/{document_id}` | Document details |
| `PATCH` | `/documents/{document_id}` | Update document metadata |
| `DELETE` | `/documents/{document_id}` | Delete document |
| `POST` | `/documents/upload` | Upload new document |
| `POST` | `/documents/{document_id}/upload` | Upload new document version |
| `POST` | `/documents/upload-scanned` | Upload scanned image as document |
| `GET` | `/documents/{document_id}/custom-fields` | Get custom field values |
| `POST` | `/documents/{document_id}/custom-fields` | Set custom field values |
| `GET` | `/documents/{document_id}/versions` | List versions |
| `GET` | `/documents/{document_id}/versions/{version_id}` | Get specific version |
| `POST` | `/documents/{document_id}/anomaly` | Flag for anomaly review |
| `GET` | `/documents/{document_id}/thumbnail-status` | OCR/thumbnail processing status |

---

## 12. Document Types

**Module:** `document_types` | **Prefix:** `/document-types`

Defines document categories (e.g., Invoice, Contract, Medical Record) that determine which custom fields attach to documents. Types are user- or group-owned. A grouped view endpoint returns types organized by owner for efficient rendering in the UI.

| Method | Path | Description |
|---|---|---|
| `GET` | `/document-types` | List document types (paginated) |
| `POST` | `/document-types` | Create document type |
| `GET` | `/document-types/grouped` | Types grouped by owner |
| `GET` | `/document-types/{type_id}` | Type details |
| `PATCH` | `/document-types/{type_id}` | Update type |
| `DELETE` | `/document-types/{type_id}` | Delete type |

---

## 13. Email Ingestion

**Module:** `emails` | **Prefix:** `/emails`

Email-to-document ingestion from multiple email protocols. Supports direct `.eml`/`.msg` file import, IMAP account connections, Microsoft Graph API (Office 365), and Gmail. Processing rules route attachments to specific folders or trigger workflows automatically. Thread browsing allows review of raw email content.

| Method | Path | Description |
|---|---|---|
| `POST` | `/emails/import` | Import .eml/.msg file |
| `GET` | `/emails/accounts` | List email accounts |
| `POST` | `/emails/accounts` | Add email account |
| `GET` | `/emails/accounts/{account_id}` | Account details |
| `PATCH` | `/emails/accounts/{account_id}` | Update account |
| `DELETE` | `/emails/accounts/{account_id}` | Remove account |
| `POST` | `/emails/accounts/{account_id}/sync` | Trigger manual sync |
| `GET` | `/emails/threads` | List email threads |
| `GET` | `/emails/threads/{thread_id}` | Thread with messages |
| `GET` | `/emails/rules` | List processing rules |
| `POST` | `/emails/rules` | Create processing rule |
| `PATCH` | `/emails/rules/{rule_id}` | Update rule |
| `DELETE` | `/emails/rules/{rule_id}` | Delete rule |

---

## 14. Encryption

**Module:** `encryption` | **Prefix:** `/encryption`

Tenant-level encryption key management. Documents can be encrypted at rest using tenant-managed keys. Key rotation re-encrypts all documents. Accessing hidden (encrypted) documents requires an admin-approved single-view decryption token with a short TTL.

| Method | Path | Description |
|---|---|---|
| `GET` | `/encryption/keys` | List encryption keys |
| `POST` | `/encryption/keys` | Create encryption key |
| `GET` | `/encryption/keys/{key_id}` | Key details |
| `DELETE` | `/encryption/keys/{key_id}` | Delete key |
| `POST` | `/encryption/keys/{key_id}/rotate` | Rotate key (re-encrypt documents) |
| `POST` | `/encryption/keys/{key_id}/set-active` | Set active key |
| `GET` | `/encryption/access-requests` | List access requests |
| `POST` | `/encryption/access-requests` | Request access to hidden document |
| `POST` | `/encryption/access-requests/{request_id}/approve` | Approve request |
| `POST` | `/encryption/access-requests/{request_id}/deny` | Deny request |
| `POST` | `/encryption/single-view-token` | Issue single-view decryption token |

---

## 15. Form Recognition

**Module:** `form_recognition` | **Prefix:** `/forms`

AI-powered structured data extraction from known form types. Templates define the layout and fields of a form type. Extraction jobs run a VLM or fine-tuned model against a document to populate structured field values. Human feedback on incorrect extractions feeds back to improve future model accuracy. Signature detection identifies signature regions on any page.

| Method | Path | Description |
|---|---|---|
| `GET` | `/forms/templates` | List form templates |
| `POST` | `/forms/templates` | Create template |
| `GET` | `/forms/templates/{template_id}` | Template details |
| `PATCH` | `/forms/templates/{template_id}` | Update template |
| `DELETE` | `/forms/templates/{template_id}` | Delete template |
| `POST` | `/forms/extract` | Run extraction on document |
| `GET` | `/forms/extractions/{extraction_id}` | Extraction results |
| `POST` | `/forms/extractions/{extraction_id}/feedback` | Submit correction feedback |
| `POST` | `/forms/detect-signatures` | Detect signatures in document page |

---

## 16. Groups

**Module:** `groups` | **Prefix:** `/groups`

User groups for shared ownership and role assignment. Tags, custom fields, and document types can be owned by a group so all members share access. Groups have associated special folders (inbox and home) automatically created on group creation.

| Method | Path | Description |
|---|---|---|
| `GET` | `/groups` | List groups (paginated) |
| `POST` | `/groups` | Create group |
| `GET` | `/groups/all` | All groups (unpaginated) |
| `GET` | `/groups/tree` | Groups as a tree |
| `GET` | `/groups/{group_id}` | Group details |
| `PATCH` | `/groups/{group_id}` | Update group |
| `DELETE` | `/groups/{group_id}` | Delete group |
| `GET` | `/groups/{group_id}/special-folders` | Group's home and inbox folders |

---

## 17. Ingestion Pipelines

**Module:** `ingestion` | **Prefix:** `/ingestion`

Automated document ingestion from external sources. Folder watcher sources monitor directories and ingest new files automatically; email connector sources pull attachments. Ingestion templates define classification rules for auto-tagging and routing incoming documents. Validation rules enforce file type, size, and naming constraints. All jobs track status and errors.

| Method | Path | Description |
|---|---|---|
| `GET` | `/ingestion/sources` | List ingestion sources |
| `POST` | `/ingestion/sources` | Create source |
| `GET` | `/ingestion/sources/{source_id}` | Source details |
| `PATCH` | `/ingestion/sources/{source_id}` | Update source |
| `DELETE` | `/ingestion/sources/{source_id}` | Delete source |
| `POST` | `/ingestion/sources/{source_id}/trigger` | Trigger manual ingestion |
| `GET` | `/ingestion/jobs` | List ingestion jobs |
| `GET` | `/ingestion/jobs/{job_id}` | Job details and status |
| `GET` | `/ingestion/templates` | List ingestion templates |
| `POST` | `/ingestion/templates` | Create template |
| `PATCH` | `/ingestion/templates/{template_id}` | Update template |
| `DELETE` | `/ingestion/templates/{template_id}` | Delete template |
| `GET` | `/ingestion/validation-rules` | List validation rules |
| `POST` | `/ingestion/validation-rules` | Create rule |
| `DELETE` | `/ingestion/validation-rules/{rule_id}` | Delete rule |

---

## 18. Physical Inventory

**Module:** `inventory` | **Prefix:** `/inventory`

Tracks the physical location of original paper documents. Each item is registered with a digital counterpart, labeled with a machine-readable code (QR or DataMatrix), and assigned to a warehouse location or container. Chain-of-custody events record every movement. Duplicate detection identifies items likely referring to the same physical document. Reconciliation reports compare physical inventory against the digital record.

| Method | Path | Description |
|---|---|---|
| `GET` | `/inventory/items` | List inventory items |
| `POST` | `/inventory/items` | Register item |
| `GET` | `/inventory/items/{item_id}` | Item details |
| `PATCH` | `/inventory/items/{item_id}` | Update item |
| `DELETE` | `/inventory/items/{item_id}` | Remove item |
| `POST` | `/inventory/items/{item_id}/generate-code` | Generate QR/DataMatrix code |
| `GET` | `/inventory/items/{item_id}/custody` | Chain-of-custody events |
| `POST` | `/inventory/items/{item_id}/custody` | Add custody event |
| `GET` | `/inventory/duplicates` | Detect duplicates |
| `POST` | `/inventory/reconcile` | Physical vs digital reconciliation |
| `GET` | `/inventory/locations` | List warehouse locations |
| `POST` | `/inventory/locations` | Create location |
| `GET` | `/inventory/locations/{location_id}` | Location details |
| `PATCH` | `/inventory/locations/{location_id}` | Update location |
| `GET` | `/inventory/containers` | List containers |
| `POST` | `/inventory/containers` | Create container |
| `GET` | `/inventory/containers/{container_id}` | Container details |
| `POST` | `/inventory/scan` | Process barcode scan event |

---

## 19. Liveness Probe

**Module:** `liveness_probe` | **Prefix:** `/probe`

Minimal liveness endpoint for container orchestration health checks. Executes a `SELECT 1` against PostgreSQL to confirm both the application process and its database connection are alive.

| Method | Path | Description |
|---|---|---|
| `GET` | `/probe/liveness` | Liveness probe — `{"status": "ok"}` |

---

## 20. Monitoring

**Module:** `monitoring` | **Prefix:** `/monitoring`

Operational observability for the platform. The health endpoint checks PostgreSQL and Redis connectivity. The metrics endpoint exports Prometheus-format counters and gauges for scraping by Prometheus, Grafana, or any compatible monitoring stack.

| Method | Path | Description |
|---|---|---|
| `GET` | `/monitoring/health` | Health check (DB + Redis) |
| `GET` | `/monitoring/metrics` | Prometheus metrics |

---

## 21. Nodes (File Tree)

**Module:** `nodes` | **Prefix:** `/nodes`

The primary document tree API powering the file-explorer UI. Provides hierarchical navigation, folder and document CRUD, breadcrumb paths, bulk move and delete, tag management on nodes, and inbox access. Nodes are the unifying abstraction over folders and documents.

| Method | Path | Scope | Description |
|---|---|---|---|
| `GET` | `/nodes` | `node:view` | List nodes (paginated, filterable) |
| `POST` | `/nodes` | `node:create` | Create folder |
| `GET` | `/nodes/{node_id}` | `node:view` | Node details |
| `PATCH` | `/nodes/{node_id}` | `node:update` | Rename or update node |
| `DELETE` | `/nodes/{node_id}` | `node:delete` | Delete node |
| `GET` | `/nodes/{node_id}/breadcrumb` | `node:view` | Breadcrumb path |
| `GET` | `/nodes/{node_id}/children` | `node:view` | Children of folder |
| `POST` | `/nodes/move` | `node:move` | Move node(s) |
| `POST` | `/nodes/bulk-delete` | `node:delete` | Delete multiple nodes |
| `POST` | `/nodes/{node_id}/tags` | `node:update` | Assign tags |
| `DELETE` | `/nodes/{node_id}/tags` | `node:update` | Remove tags |
| `GET` | `/nodes/inbox` | `node:view` | User inbox contents |

---

## 22. OCR Proxy

**Module:** `ocr_proxy` | **Prefix:** `/ocr-proxy`

Server-side reverse proxy for Vision Language Model APIs. Allows browser clients to call AI OCR providers without exposing API keys in client-side code or hitting CORS restrictions. The server authenticates the caller with a JWT, then forwards requests to the configured upstream provider using the appropriate API key from server configuration.

**Supported Providers:**

| Method | Path | Header Required | Provider |
|---|---|---|---|
| `GET` | `/ocr-proxy/ollama/tags` | — | Ollama model list |
| `POST` | `/ocr-proxy/ollama/chat` | — | Ollama chat/VLM inference |
| `POST` | `/ocr-proxy/anthropic/messages` | `X-Anthropic-Api-Key` | Anthropic Claude |
| `POST` | `/ocr-proxy/openai/chat/completions` | `X-OpenAI-Api-Key` | OpenAI GPT-4 Vision |
| `POST` | `/ocr-proxy/azure-openai/chat/completions` | `X-Azure-Api-Key`, `X-Azure-Endpoint`, `X-Azure-Deployment` | Azure OpenAI |

---

## 23. Permissions

**Module:** `permissions` | **Prefix:** `/permissions`

Read-only enumeration of all available permission scopes. Used by the frontend to populate role-editing UIs. Returns both flat lists and category-grouped views of every scope constant defined in the platform.

| Method | Path | Description |
|---|---|---|
| `GET` | `/permissions` | All scopes (flat list) |
| `GET` | `/permissions/grouped` | Scopes grouped by category |

---

## 24. ABAC Policies

**Module:** `policies` | **Prefix:** `/policies`

Attribute-Based Access Control engine. Policies are written in a DSL and evaluated against `PolicyContext` objects containing user attributes, resource attributes, and environment context (IP, time, etc.). Policies can be submitted for approval before taking effect. Department-level grants provide a simpler access control layer on top of the full policy engine. Analytics surfaces policy evaluation rates and denial patterns.

| Method | Path | Description |
|---|---|---|
| `GET` | `/policies` | List policies |
| `POST` | `/policies` | Create policy |
| `GET` | `/policies/{policy_id}` | Policy details |
| `PATCH` | `/policies/{policy_id}` | Update policy |
| `DELETE` | `/policies/{policy_id}` | Delete policy |
| `POST` | `/policies/{policy_id}/submit-for-approval` | Submit for approval |
| `POST` | `/policies/{policy_id}/approve` | Approve |
| `POST` | `/policies/{policy_id}/reject` | Reject |
| `POST` | `/policies/evaluate` | Evaluate against request context |
| `POST` | `/policies/evaluate-dry-run` | Dry-run evaluation (no audit log) |
| `GET` | `/policies/evaluation-logs` | Evaluation history |
| `GET` | `/policies/department-grants` | Department access grants |
| `POST` | `/policies/department-grants` | Create department grant |
| `DELETE` | `/policies/department-grants/{grant_id}` | Delete grant |
| `GET` | `/policies/analytics` | Policy usage analytics |

---

## 25. Portfolios

**Module:** `portfolios` | **Prefix:** `/portfolios`

Top-level groupings of related cases (e.g., a client matter containing multiple legal case files). Portfolios support access grants for user/group sharing. The portfolio → case → document hierarchy provides a three-level logical organization structure above the physical folder tree.

| Method | Path | Description |
|---|---|---|
| `GET` | `/portfolios` | List portfolios |
| `POST` | `/portfolios` | Create portfolio |
| `GET` | `/portfolios/{portfolio_id}` | Portfolio details |
| `PATCH` | `/portfolios/{portfolio_id}` | Update portfolio |
| `DELETE` | `/portfolios/{portfolio_id}` | Delete portfolio |
| `GET` | `/portfolios/{portfolio_id}/cases` | Cases in portfolio |
| `POST` | `/portfolios/{portfolio_id}/access` | Grant access |
| `DELETE` | `/portfolios/{portfolio_id}/access/{grant_id}` | Revoke access |

---

## 26. Preferences

**Module:** `preferences` | **Prefix:** `/preferences`

Per-user and system-wide UI/locale preferences. Settings include timezone, language, date format, number format (decimal separator), and theme. System-wide defaults are the fallback when user preferences are not set. Only admins can modify system defaults.

| Method | Path | Description |
|---|---|---|
| `GET` | `/preferences` | Current user's preferences |
| `PATCH` | `/preferences` | Update user preferences |
| `GET` | `/preferences/system` | System-wide defaults |
| `PATCH` | `/preferences/system` | Update system defaults (admin) |

---

## 27. Provenance & Chain-of-Custody

**Module:** `provenance` | **Prefix:** `/provenance`

Cryptographic tamper-detection for document records. Each provenance event is SHA-512 hashed and linked to the previous event, forming an immutable chain. Any modification to a historical record breaks the chain and is detected by the verify endpoint. The chain-of-custody report resolves actor IDs to names and provides a human-readable audit trail.

| Method | Path | Description |
|---|---|---|
| `GET` | `/provenance/{document_id}` | List provenance records |
| `POST` | `/provenance/{document_id}` | Record a provenance event |
| `GET` | `/provenance/{document_id}/chain` | Full chain-of-custody with actor resolution |
| `POST` | `/provenance/{document_id}/verify` | Verify chain integrity |

---

## 28. Document Quality

**Module:** `quality` | **Prefix:** `/quality`

Rule-based and AI-powered document quality management. Quality rules define minimum thresholds (DPI, text coverage percentage, image sharpness, skew angle). Assessments run rules against a document and produce a scored result with per-metric details. Issues track documents that failed assessment. The VLM assessment endpoint uses Ollama's Qwen-VL model for visual quality evaluation beyond what metric thresholds can express.

| Method | Path | Description |
|---|---|---|
| `GET` | `/quality/rules` | List quality rules |
| `POST` | `/quality/rules` | Create rule |
| `PATCH` | `/quality/rules/{rule_id}` | Update rule |
| `DELETE` | `/quality/rules/{rule_id}` | Delete rule |
| `GET` | `/quality/assessments` | List assessments |
| `POST` | `/quality/assess` | Run assessment on document |
| `GET` | `/quality/assessments/{assessment_id}` | Assessment results with metrics |
| `GET` | `/quality/issues` | List quality issues |
| `PATCH` | `/quality/issues/{issue_id}` | Update issue (resolve, assign) |
| `GET` | `/quality/stats` | Aggregated quality statistics |
| `POST` | `/quality/vlm-assess` | VLM-powered visual assessment |

---

## 29. Roles

**Module:** `roles` | **Prefix:** `/roles`

Authorization roles with assigned permission scopes. Roles support soft-delete (archive) rather than hard deletion to preserve referential integrity in audit logs. Archived roles can be restored. All mutations are audited.

| Method | Path | Description |
|---|---|---|
| `GET` | `/roles` | List roles (optionally include archived) |
| `POST` | `/roles` | Create role |
| `GET` | `/roles/all` | All roles (unpaginated) |
| `GET` | `/roles/{role_id}` | Role details |
| `PATCH` | `/roles/{role_id}` | Update role |
| `DELETE` | `/roles/{role_id}` | Archive (soft-delete) role |
| `POST` | `/roles/{role_id}/restore` | Restore archived role |
| `GET` | `/roles/{role_id}/scopes` | Scopes assigned to role |

---

## 30. Routing Rules

**Module:** `routing` | **Prefix:** `/routing`

Condition-based automatic document routing. Rules evaluate conditions on document metadata (type, tags, custom field values, filename pattern) and execute actions (move to folder, assign tag, trigger workflow, set custom field). Dry-run mode previews which actions would fire without executing them. Routing logs provide a per-document audit of which rules matched and what was done.

| Method | Path | Description |
|---|---|---|
| `GET` | `/routing/rules` | List routing rules |
| `POST` | `/routing/rules` | Create rule |
| `GET` | `/routing/rules/{rule_id}` | Rule details |
| `PATCH` | `/routing/rules/{rule_id}` | Update rule |
| `DELETE` | `/routing/rules/{rule_id}` | Delete rule |
| `POST` | `/routing/rules/{rule_id}/execute` | Execute rule against document |
| `POST` | `/routing/rules/{rule_id}/dry-run` | Dry-run rule against document |
| `GET` | `/routing/logs` | Routing execution logs |

---

## 31. Scanners

**Module:** `scanners` | **Prefix:** `/scanners`

Physical scanner hardware lifecycle management. Scanners are discovered on the local network (zeroconf/mDNS), registered in the DB, and assigned API keys for authentication. Scan profiles store DPI, color mode, and paper size presets. Scan jobs are created, tracked, and the resulting document IDs retrieved. A dashboard and usage stats endpoint provide operational visibility.

> **Route ordering note:** All static paths (`/jobs`, `/profiles`, `/settings`, `/dashboard`, `/stats`) are registered before `/{scanner_id}` to prevent FastAPI from capturing them as scanner IDs.

| Method | Path | Description |
|---|---|---|
| `GET` | `/scanners/discover` | Discover network scanners |
| `GET` | `/scanners` | List registered scanners |
| `POST` | `/scanners` | Register scanner |
| `GET` | `/scanners/jobs` | List scan jobs |
| `POST` | `/scanners/jobs` | Create and start scan job |
| `GET` | `/scanners/jobs/{job_id}` | Scan job details |
| `POST` | `/scanners/jobs/{job_id}/cancel` | Cancel scan job |
| `GET` | `/scanners/jobs/{job_id}/result` | Scan result (document IDs) |
| `GET` | `/scanners/profiles` | List scan profiles |
| `POST` | `/scanners/profiles` | Create profile |
| `GET` | `/scanners/profiles/{profile_id}` | Profile details |
| `PATCH` | `/scanners/profiles/{profile_id}` | Update profile |
| `DELETE` | `/scanners/profiles/{profile_id}` | Delete profile |
| `GET` | `/scanners/settings` | Global scanner settings |
| `PATCH` | `/scanners/settings` | Update settings |
| `GET` | `/scanners/dashboard` | Scanner dashboard |
| `GET` | `/scanners/stats` | Usage statistics |
| `GET` | `/scanners/{scanner_id}` | Scanner details |
| `PATCH` | `/scanners/{scanner_id}` | Update scanner |
| `DELETE` | `/scanners/{scanner_id}` | Remove registration |
| `POST` | `/scanners/{scanner_id}/api-key` | Generate/rotate API key |
| `GET` | `/scanners/{scanner_id}/status` | Real-time status |
| `GET` | `/scanners/{scanner_id}/capabilities` | Scanner capabilities |
| `POST` | `/scanners/{scanner_id}/refresh-capabilities` | Refresh from device |

---

## 32. Scanning Projects

**Module:** `scanning_projects` | **Prefix:** `/scanning-projects`

Enterprise-scale digitization project management. Organizes large scanning initiatives into projects with phases, batches, and milestones. Manages operator schedules, shift assignments, scanning locations, equipment maintenance, and operator certifications. Tracks costs against budgets, defines SLAs with automated alert escalation, and supports batch priority queues and workload forecasting. AI analysis provides automated project health insights. Reporting includes burndown charts, velocity charts, multi-location dashboards, and gamification leaderboards.

This module exposes over 70 endpoints. Key endpoint groups:

| Group | Paths | Description |
|---|---|---|
| Projects | `/scanning-projects`, `/{project_id}` | CRUD, metrics, dashboard, burndown, velocity |
| Batches | `/{project_id}/batches` | Create, list, start-scan, complete-scan, documents |
| Milestones | `/{project_id}/milestones` | CRUD |
| Phases | `/{project_id}/phases` | CRUD |
| QC | `/{project_id}/qc/pending`, `/qc/samples` | QC sample management |
| Sessions | `/{project_id}/sessions` | Scanning sessions (start/end) |
| Issues | `/{project_id}/issues` | Issue tracking |
| Costs | `/{project_id}/costs`, `/costs/summary` | Cost entries and summary |
| Budget | `/{project_id}/budget` | Budget management |
| SLAs | `/{project_id}/slas`, `/sla-alerts` | SLA definitions and alerts |
| Snapshots | `/{project_id}/snapshots` | Progress snapshots |
| Locations | `/scanning-projects/locations` | Scanning locations |
| Shifts | `/scanning-projects/shifts`, `/shift-assignments` | Operator shift scheduling |
| Maintenance | `/scanning-projects/maintenance` | Equipment maintenance |
| Certifications | `/scanning-projects/certifications` | Operator certifications |
| Capacity | `/{project_id}/capacity-plans` | Capacity planning |
| Contracts | `/{project_id}/contracts` | Contract management |
| Forecasts | `/{project_id}/workload-forecasts` | Workload forecasting |
| Analytics | `/{project_id}/ai-analysis`, `/reports/daily`, `/reports/weekly` | AI analysis, HTML/PDF reports |
| Gamification | `/gamification/leaderboard`, `/gamification/performance` | Operator leaderboards |

---

## 33. Search

**Module:** `search` | **Prefix:** `/search`

Combined full-text and metadata search. Queries are run across document title and OCR-extracted content using PostgreSQL full-text search. Results can be filtered by document type, tags, and custom field values. Pagination and multi-column sorting (including by custom field name) are supported. The response includes custom field metadata for the matched document types, enabling the UI to render dynamic columns.

| Method | Path | Description |
|---|---|---|
| `POST` | `/search/` | Search documents with FTS, type, tag, and custom field filters |

**Request body:**
```json
{
  "query": "invoice acme",
  "document_type_id": "uuid",
  "tag_ids": ["uuid1"],
  "custom_field_filters": {"Invoice Amount": {"gte": 1000}},
  "page": 1,
  "page_size": 20,
  "order_by": "created_at",
  "order": "desc"
}
```

---

## 34. Segmentation

**Module:** `segmentation` | **Prefix:** `/segmentation`

Automatic multi-document boundary detection for batch scans. When a single scan contains multiple documents (common in high-volume digitization), a Celery segmentation job analyzes the image and identifies document boundaries. Human reviewers inspect segments, approve or reject them, and convert approved segments into standalone document records queued for OCR.

| Method | Path | Description |
|---|---|---|
| `POST` | `/segmentation/analyze` | Start async segmentation job |
| `GET` | `/segmentation/jobs` | List segmentation jobs |
| `GET` | `/segmentation/jobs/{job_id}` | Job status |
| `GET` | `/segmentation/segments` | List segments (filterable) |
| `GET` | `/segmentation/segments/{segment_id}` | Segment details |
| `PATCH` | `/segmentation/segments/{segment_id}` | Update segment |
| `POST` | `/segmentation/segments/{segment_id}/verify` | Approve or reject segment |
| `POST` | `/segmentation/segments/{segment_id}/create-document` | Convert to document |
| `DELETE` | `/segmentation/segments/{segment_id}` | Delete segment |
| `GET` | `/segmentation/stats` | Segmentation statistics |

---

## 35. Serial Numbers

**Module:** `serial_numbers` | **Prefix:** `/serial-numbers`

Auto-incrementing serial number assignment for documents using configurable pattern sequences. Patterns support placeholders: `{YEAR}`, `{MONTH}`, `{SEQ:N}` (zero-padded counter), `{DOCTYPE}`. Sequences track a current counter value and can be reset. Documents can be assigned serials automatically on upload, manually, or in bulk. Lookup by serial number acts as a cross-reference index.

| Method | Path | Description |
|---|---|---|
| `GET` | `/serial-numbers/sequences` | List sequences |
| `GET` | `/serial-numbers/sequences/{sequence_id}` | Sequence details |
| `POST` | `/serial-numbers/sequences` | Create sequence |
| `PATCH` | `/serial-numbers/sequences/{sequence_id}` | Update sequence |
| `DELETE` | `/serial-numbers/sequences/{sequence_id}` | Delete sequence |
| `POST` | `/serial-numbers/assign/{document_id}` | Auto-assign serial |
| `POST` | `/serial-numbers/assign-manual` | Manual serial assignment |
| `POST` | `/serial-numbers/assign-bulk` | Bulk assignment |
| `GET` | `/serial-numbers/document/{document_id}` | Serial for document |
| `GET` | `/serial-numbers/lookup/{serial_number}` | Document by serial |
| `GET` | `/serial-numbers/search` | Search by serial number |
| `DELETE` | `/serial-numbers/document/{document_id}` | Remove serial from document |
| `POST` | `/serial-numbers/preview-pattern` | Preview pattern output |

---

## 36. Shared Nodes

**Module:** `shared_nodes` | **Prefix:** `/shared-nodes`

Document and folder sharing between users, groups, and roles. A share grant specifies which node IDs are shared and with which users, groups, or roles. The access endpoint returns the full set of principals who can access a given node and through which roles.

| Method | Path | Scope | Description |
|---|---|---|---|
| `GET` | `/shared-nodes` | `node:view` | Nodes shared with current user |
| `POST` | `/shared-nodes` | `shared_node:create` | Create share grants |
| `GET` | `/shared-nodes/access/{node_id}` | `shared_node:view` | Access details for node |
| `PATCH` | `/shared-nodes/access/{node_id}` | `shared_node:update` | Sync access for node |

---

## 37. Tags

**Module:** `tags` | **Prefix:** `/tags`

Colored tags for visual document categorization. Tags are user- or group-owned, enforcing that only authorized users can modify them. The `all` endpoint returns the complete tag list for dropdown/autocomplete UIs without pagination overhead.

| Method | Path | Scope | Description |
|---|---|---|---|
| `GET` | `/tags/all` | `tag:select` | All tags (unpaginated) |
| `GET` | `/tags/` | `tag:view` | Tags (paginated) |
| `GET` | `/tags/{tag_id}` | `tag:view` | Tag details |
| `POST` | `/tags/` | `tag:create` | Create tag |
| `PATCH` | `/tags/{tag_id}` | `tag:update` | Update tag |
| `DELETE` | `/tags/{tag_id}` | `tag:delete` | Delete tag |

---

## 38. OCR Tasks

**Module:** `tasks` | **Prefix:** `/tasks`

Direct OCR dispatch endpoint. Triggers asynchronous OCR for a specific document by sending a task to the Celery `ocr` queue. Supports three engine modes: `tesseract` (ocrmypdf), `qwen-vl` (Ollama VLM), and `auto` (server decides based on configuration).

| Method | Path | Scope | Description |
|---|---|---|---|
| `POST` | `/tasks/ocr` | `task:ocr` | Trigger OCR for document |

**Request body:**
```json
{
  "document_id": "uuid",
  "lang": "eng",
  "engine": "auto"
}
```

---

## 39. Tenants

**Module:** `tenants` | **Prefix:** `/tenants`

Multi-tenant administration at two access levels. Tenant-scoped endpoints let tenant admins manage their own profile, branding, and settings. System-admin endpoints support full tenant lifecycle: creation, configuration, per-tenant storage backends (with connectivity verification), AI provider configuration, subscription management, and one-shot provisioning that creates the tenant, storage config, AI config, subscription, and initial admin user atomically.

**Tenant-scoped (require `tenant:admin`):**

| Method | Path | Description |
|---|---|---|
| `GET` | `/tenants/current` | Current tenant details |
| `PATCH` | `/tenants/current` | Update tenant |
| `GET` | `/tenants/current/branding` | Branding settings |
| `PATCH` | `/tenants/current/branding` | Update branding |
| `GET` | `/tenants/current/settings` | Tenant settings |
| `PATCH` | `/tenants/current/settings` | Update settings |
| `GET` | `/tenants/current/usage` | Usage statistics |

**System-admin (`system:admin`):**

| Method | Path | Description |
|---|---|---|
| `GET` | `/tenants/` | List all tenants |
| `POST` | `/tenants/` | Create tenant |
| `GET` | `/tenants/{tenant_id}` | Tenant details |
| `PATCH` | `/tenants/{tenant_id}` | Update tenant |
| `GET` | `/tenants/{tenant_id}/storage` | Storage configuration |
| `PUT` | `/tenants/{tenant_id}/storage` | Update storage config |
| `POST` | `/tenants/{tenant_id}/storage/verify` | Verify storage connectivity |
| `GET` | `/tenants/{tenant_id}/ai` | AI provider config |
| `PUT` | `/tenants/{tenant_id}/ai` | Update AI config |
| `POST` | `/tenants/{tenant_id}/ai/reset-tokens` | Reset monthly token usage |
| `GET` | `/tenants/{tenant_id}/subscription` | Subscription details |
| `PUT` | `/tenants/{tenant_id}/subscription` | Update subscription |
| `POST` | `/tenants/provision` | Full tenant provisioning |

---

## 40. User Home

**Module:** `user_home` | **Prefix:** (root paths)

Aggregated home page data layer for the current authenticated user. Consolidates workflow tasks, recent documents, favorites, notifications, calendar events, recent searches, and an activity feed into a single home endpoint. Notification management (mark-read, mark-all-read) and favorites CRUD are also exposed here.

| Method | Path | Description |
|---|---|---|
| `GET` | `/users/me/home` | Aggregated home page data |
| `GET` | `/documents/recent` | Recently accessed documents |
| `GET` | `/users/me/favorites` | Favorites list |
| `POST` | `/users/me/favorites` | Add to favorites |
| `DELETE` | `/users/me/favorites/{favorite_id}` | Remove from favorites |
| `GET` | `/notifications` | List notifications |
| `POST` | `/notifications/{notification_id}/read` | Mark notification read |
| `POST` | `/notifications/read-all` | Mark all read |
| `GET` | `/calendar/events` | Calendar events for date range |
| `GET` | `/search/recent` | Recent search history |
| `DELETE` | `/search/recent` | Clear search history |
| `GET` | `/activity` | Activity feed |

---

## 41. Users

**Module:** `users` | **Prefix:** `/users`

Full user management with audit-wrapped mutations. Includes listing users in the same group context, retrieving group-shared special folders (home and inbox) for the current user, and handling account deletion via background Celery task (with graceful fallback when Redis is unavailable).

| Method | Path | Scope | Description |
|---|---|---|---|
| `GET` | `/users/group-homes` | `node:view` | Current user's group home folders |
| `GET` | `/users/group-inboxes` | `node:view` | Current user's group inboxes |
| `GET` | `/users/me` | — | Current user profile |
| `GET` | `/users/me/home` | — | Home page data |
| `GET` | `/users/group-users` | — | Users in shared groups |
| `GET` | `/users/user-groups` | — | Groups current user belongs to |
| `GET` | `/users/` | `user:view` | List users (paginated) |
| `GET` | `/users/all` | `user:select` | All users (unpaginated) |
| `POST` | `/users/` | `user:create` | Create user |
| `GET` | `/users/{user_id}` | `user:view` | User details |
| `DELETE` | `/users/{user_id}` | `user:delete` | Delete user |
| `PATCH` | `/users/{user_id}` | `user:update` | Update user |
| `POST` | `/users/change-password` | `user:update` | Change password |

---

## 42. Workflows

**Module:** `workflows` | **Prefix:** `/workflows`

Multi-step document approval and review workflows powered by Prefect. Workflow definitions specify ordered steps with assignee types (user, role, group), deadlines, and escalation rules. Instances are started for specific documents and proceed through steps as assignees take actions. The SLA subsystem monitors step deadlines and raises alerts at configurable warning/breach thresholds. A compliance dashboard provides real-time visibility into workflow health across the organization.

| Method | Path | Description |
|---|---|---|
| `GET` | `/workflows/` | List workflow definitions |
| `POST` | `/workflows/` | Create workflow definition |
| `GET` | `/workflows/executions/` | List execution instances |
| `GET` | `/workflows/{workflow_id}` | Workflow details with steps |
| `POST` | `/workflows/{workflow_id}/start` | Start workflow for document |
| `GET` | `/workflows/instances/pending` | Pending tasks for current user |
| `GET` | `/workflows/tasks/assigned` | Approval requests assigned to user |
| `POST` | `/workflows/instances/{instance_id}/actions` | Process step action |
| `POST` | `/workflows/instances/{instance_id}/cancel` | Cancel workflow |
| `POST` | `/workflows/instances/{instance_id}/resume` | Resume with approval data |
| `GET` | `/workflows/instances/{instance_id}/status` | Instance status |
| `POST` | `/workflows/approval-requests/{request_id}/delegate` | Delegate request |
| `GET` | `/workflows/sla/dashboard` | SLA compliance dashboard |
| `GET` | `/workflows/sla/metrics` | SLA task metrics (paginated) |
| `POST` | `/workflows/sla/alerts/{alert_id}/acknowledge` | Acknowledge SLA alert |
| `GET` | `/workflows/sla/configs` | SLA configurations |
| `POST` | `/workflows/sla/configs` | Create SLA configuration |
| `GET` | `/workflows/sla/alerts` | SLA alerts (filterable) |

---

## Modules Without HTTP Routers

Three modules implement internal logic with no direct HTTP surface:

| Module | Role |
|---|---|
| `ownership` | DB model for resource ownership (user/group); consumed by tags, custom_fields, document_types |
| `page_mngm` | Page manipulation operations (rotate, reorder, extract); surfaced through document API and Celery tasks |
| `special_folders` | Auto-creation of per-user and per-group home/inbox folders on creation; surfaced through `/nodes` and `/users` |
