# Bulk Scanning Feature Roadmap

**Derived from:** `docs/research/bulk-scanning-competitive-analysis.md`  
**Date:** 2026-06-13  
**Goal:** Make dArchiva the unambiguous default choice for bulk scanning and document management projects.

---

## P0 — Ship these or lose the deal

These are table-stakes for any serious bulk scanning customer. Missing any one blocks adoption.

### P0-1: dArchiva Scan Agent (Desktop Client)

**Problem:** Browsers cannot access TWAIN/WIA/ISIS/SANE scanner APIs due to sandbox restrictions.  
**Solution:** Lightweight cross-platform desktop agent that:
- Exposes a **local REST API on `localhost:7780`** — the web app communicates with it via `http://localhost:7780`
- Implements TWAIN (Windows/Mac) and SANE (Linux) bridging via Dynamsoft Device Web Service SDK or equivalent
- Queues completed scans locally and syncs to dArchiva when connectivity allows (offline-first)
- Auto-updates silently in the background

**Technology options:**
- Electron wrapper around existing web UI + native addon for scanner access
- Go/Rust native binary with embedded HTTP server (smaller, faster, no Electron overhead)
- **Recommended:** Go binary (`darchiva-scan-agent`) — single binary, 10 MB, no runtime dependency

**API surface (localhost):**
```
GET  /devices              → list attached scanners
POST /scan                 → trigger scan, returns job_id
GET  /jobs/{job_id}        → poll scan status + get image URLs
POST /jobs/{job_id}/upload → push completed images to dArchiva API
GET  /health               → liveness check from web app
```

**Deliverables:**
- [ ] Windows installer (.msi), macOS .dmg, Linux .deb/.rpm
- [ ] Auto-launch on login, system tray icon
- [ ] Web app detects agent presence via `/health` on startup
- [ ] Scan profile sync from server (DPI, colour mode, ADF vs. flatbed, paper size)

---

### P0-2: Automated Image Quality Scoring Pipeline

**Problem:** Operators currently submit scans with no automated quality gate. Bad scans reach storage.  
**Solution:** Per-page quality scoring at ingestion with configurable rejection thresholds.

**Implementation:**

```python
# papermerge/core/features/scanning_projects/quality_pipeline.py

async def assess_page_quality(image_bytes: bytes, config: QualityConfig) -> PageQualityResult:
    """Score a scanned page and return accept/reject decision."""
    # Option A: Google Cloud Document AI (cloud)
    # Option B: Local pipeline (self-hostable)
    ...
```

**Self-hostable pipeline (no cloud dependency):**
1. **Blur detection:** Laplacian variance < 100 → `blurry` defect
2. **Deskew check:** Measure skew angle; if |angle| > 1° → deskew + flag
3. **Glare detection:** % pixels with brightness > 245 in > 5% of image area → `glare` defect
4. **Document cutoff:** Detect if content touches image border → `document_cutoff`
5. **Noise floor:** % dark pixels in nominally-white background → `background_noise`
6. **Composite score:** weighted average → `quality_score` in [0.0, 1.0]

**Cloud option (higher accuracy):**
- Google Cloud Document AI `ImageQualityScores` API
- Returns `quality_score` float + `detected_defects[]` array
- Suitable for high-value document types (legal, financial)

**Configuration (per-project):**
```yaml
quality:
  min_score: 0.75          # pages below this → rescan queue
  auto_reject_defects:     # these defects always trigger rescan
    - document_cutoff
    - glare
  flag_for_review_defects: # these go to supervisor review
    - text_too_small
    - shadow
  min_dpi: 300             # enforced at scan time
```

**Deliverables:**
- [ ] `QualityPipeline` service with pluggable backends (local / GCP Document AI / LiteLLM)
- [ ] Per-page quality result stored in DB (`scan_jobs` → `page_events` table)
- [ ] Rescan queue UI — operator sees rejected pages and reasons
- [ ] Project-level quality config in scanning project settings

---

### P0-3: Hardware-Agnostic Scanner Driver Support

**Problem:** Each scanner brand requires different setup; production scanners use ISIS, not TWAIN.  
**Solution:** Protocol detection and routing in the Scan Agent.

**Driver priority:**
1. **ISIS** — required for OPEX, Kodak Alaris, Panasonic production scanners (>100 ppm)
2. **TWAIN 2.x** — required for Fujitsu, Canon, Brother desktop/workgroup scanners
3. **WIA** — Windows fallback for consumer scanners
4. **SANE** — Linux/Mac for HP, Epson, Brother

**Scan profile settings surfaced to users:**
- Resolution (150/200/300/400/600 DPI)
- Colour mode (B&W, greyscale, colour)
- Paper size (A4, Letter, Legal, A3, custom)
- Duplex mode (simplex/duplex/auto)
- ADF vs. flatbed
- Blank page detection threshold
- Auto-crop to content

---

## P1 — Ship in next quarter

### P1-1: Barcode/QR-Based Document Tracking & Dedup

**Problem:** No mechanism to detect re-scanning. Physical documents have no digital identity before scanning.  
**Solution:** Pre-scan barcode labelling workflow.

**Workflow:**
1. Before physical sorting, supervisor prints barcode sheets from dArchiva (batch of sequential IDs)
2. Physical separator sheets are inserted between documents or affixed to covers
3. At scan time, the Scan Agent reads barcode from ADF scan stream and auto-assigns document identity
4. On barcode re-detection: lookup in DB → return existing document location → operator prompted: *"Already scanned — Batch #42, 2026-06-01. Skip?"*

**Barcode format:** Code 128 or QR for document ID, plus a project/batch prefix for human readability.

**Dedup layers (in order of execution):**
1. Barcode match → exact duplicate, block immediately
2. SHA-256 file hash → exact byte match, block
3. Perceptual hash (pHash, Hamming distance < 10) → near-duplicate, flag for review
4. Serial number lookup (`document_serial_numbers` table) → soft duplicate check

**Deliverables:**
- [ ] Barcode label generation endpoint (`POST /scanning-projects/{id}/barcode-labels`)
- [ ] Scan Agent barcode reader (Zxing or built-in camera decode)
- [ ] Dedup pipeline in ingestion worker with configurable strictness
- [ ] Duplicate detection result surfaced to operator UI in real-time

---

### P1-2: Intelligent Exception Handling

**Problem:** Batches with quality failures currently halt or silently pass through.  
**Solution:** Non-blocking exception routing — bad pages are quarantined, good pages continue.

**Exception types:**
- `missing_signature` — signature field detected (OCR) but empty
- `incomplete_set` — expected page count not met (configurable per document type)
- `barcode_unreadable` — separator barcode detected but OCR failed
- `quality_rejected` — quality score below threshold (from P0-2)
- `orientation_error` — page appears to be upside down or sideways

**Routing rules (configurable per project):**
```
RULE: quality_rejected → auto-add to rescan_queue (non-blocking)
RULE: missing_signature → route to supervisor_review_queue
RULE: incomplete_set → halt batch, notify operator + supervisor
RULE: barcode_unreadable → auto-assign sequence number, flag for QC
```

**Deliverables:**
- [ ] `exception_events` table (document_id, exception_type, resolution, resolved_by)
- [ ] Exception routing rules in project settings
- [ ] Operator exception queue view (see only their flagged pages)
- [ ] Supervisor exception overview (all unresolved exceptions across all operators)

---

### P1-3: Multi-Source Ingestion

**Problem:** dArchiva ingests from scanners and file upload. Competitors support email, fax, hot folders, mobile.  
**Solution:** Extend ingestion pipeline (already partially built) with new source types.

**Source types to add (email already in models — needs worker):**
- **Email polling** (`email_accounts` table exists) — worker polls IMAP, extracts PDF/image attachments, routes to inbox folder
- **Hot folder watcher** — OS-level directory monitor; any file dropped in watched folder is auto-ingested
- **Mobile capture** — PWA camera capture with perspective correction (no native app required for this)
- **Webhook push** — third-party systems POST documents to `POST /ingestion/webhook/{source_id}`

**Deliverables:**
- [ ] Email ingestion worker (Celery task polling `email_accounts`)
- [ ] Hot folder watcher daemon in Scan Agent
- [ ] Webhook ingestion endpoint with HMAC signature verification
- [ ] Ingestion source dashboard (status, last sync, documents ingested, errors)

---

### P1-4: Supervisor Performance Dashboard

**Problem:** No visibility into operator throughput, quality, or idle time.  
**Solution:** Real-time supervisor operations view with per-operator KPIs.

**Data model additions:**

```sql
-- Operator shift tracking
CREATE TABLE operator_sessions (
    id          UUID PRIMARY KEY,
    operator_id UUID REFERENCES users(id),
    project_id  UUID REFERENCES scanning_projects(id),
    location_id UUID REFERENCES locations(id),
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    workstation TEXT
);

-- Per-page events for granular metrics
CREATE TABLE page_scan_events (
    id            UUID PRIMARY KEY,
    scan_job_id   UUID REFERENCES scan_jobs(id),
    operator_id   UUID REFERENCES users(id),
    event_type    TEXT NOT NULL, -- scanned, accepted, rejected, rescanned
    quality_score FLOAT,
    defects       JSONB,
    occurred_at   TIMESTAMPTZ NOT NULL
);
```

**KPIs surfaced:**

| Metric | Formula |
|--------|---------|
| Pages/hour | `COUNT(page_events WHERE type=accepted) / session_hours` |
| Rescan rate | `COUNT(rescanned) / COUNT(scanned) * 100` |
| First-pass yield | `COUNT(accepted_first_attempt) / COUNT(scanned) * 100` |
| Idle time | `SUM(gaps between batch completions)` |
| SLA compliance | `COUNT(batches_on_time) / COUNT(batches_due) * 100` |

**Dashboard views:**
1. **Live ops** — map/grid of active operators with real-time page count
2. **Operator leaderboard** — sortable by any KPI for current shift/day/week
3. **Batch pipeline** — Kanban view: Unassigned → In Progress → QC → Complete
4. **Alerts** — operator idle > 15 min, rescan rate > 10%, batch SLA breach imminent

---

## P2 — Competitive differentiators

### P2-1: Camera Capture Mode (Overhead/Desk Camera)

For oversized documents (maps, posters, engineering drawings) that don't fit flatbed scanners.

**Capture flow:**
1. Operator positions document under overhead camera (or against copy stand)
2. Tap foot pedal (→ keyboard shortcut) to capture
3. Platform auto-detects document corners (OpenCV contour detection)
4. Perspective correction applied (homographic transform)
5. DPI normalised using calibration card or known reference
6. Quality check (same pipeline as scanner output)
7. Uploaded as standard page — indistinguishable from scanner output in storage

**Calibration:** First-use wizard places calibration card in frame to establish pixel-to-mm ratio for DPI calculation.

**Deliverables:**
- [ ] Camera capture mode in Scan Agent (UVC camera, libgphoto2 for DSLR)
- [ ] OpenCV perspective correction pipeline
- [ ] Foot pedal / hotkey trigger (configurable key binding)
- [ ] DPI calibration wizard

---

### P2-2: Multi-Image Document Stitching

For large documents captured in multiple overlapping sections.

**Implementation:**

```python
import cv2

def stitch_document_pages(images: list[np.ndarray]) -> np.ndarray:
    stitcher = cv2.Stitcher.create(cv2.Stitcher_SCANS)
    status, result = stitcher.stitch(images)
    if status != cv2.Stitcher_OK:
        raise StitchingError(f"Stitcher failed with status {status}")
    return autocrop_to_content(result)
```

**Requirements for reliable stitching:**
- ≥20% overlap between adjacent captures
- Consistent, even lighting (overhead diffused lamp recommended)
- `Stitcher_SCANS` mode (planar, not panoramic projection)

**UI flow:**
1. Operator marks a capture session as "multi-image document"
2. Captures 2–N overlapping images (foot pedal for each)
3. Preview stitched result; accept or retake individual images
4. Final stitched image submitted as single page to dArchiva

**Fallback:** If automatic stitching fails, images remain as separate pages with a "pending manual assembly" flag.

---

### P2-3: Foot Pedal & Hotkey Trigger Support

Foot pedals register as USB HID keyboard devices — no special drivers needed.

**Required configuration in Scan Agent:**
```json
{
  "hotkeys": {
    "scan_next_page": "F9",
    "accept_page": "F10",
    "reject_page": "F11",
    "end_batch": "F12",
    "capture_camera": "Space"
  }
}
```

Configurable via Scan Agent settings UI. Works with any foot pedal that emits keyboard events (e.g., Olympus RS-31H, Infinity IN-USB-2, generic USB pedals).

---

### P2-4: Adaptive Deskewing in Pre-Processing

Replace any Hough Transform deskewing with adaptive algorithm (97.6% vs 72.2% accuracy).

**Implementation options:**
- `unpaper` (open-source, C) — mature, production-tested, handles severe skew
- `ocrmypdf --deskew` (wraps `unpaper`) — easy integration point
- Custom: scikit-image `hough_line_peaks` with probabilistic RANSAC fitting (academic approach from F3)

**Integration point:** `papermerge/core/features/scanning_projects/image_processing.py` — add as a pre-processing step before OCR.

---

### P2-5: Virtual Rebundling & Restack UI

**Problem:** Physical bundles are immutable post-scan, but logical organisation needs to change.  
**Solution:** Drag-and-drop virtual bundle editor.

**Operations:**
- **Restack** — reorder pages within a batch (drag page thumbnails)
- **Rebundle** — move pages between batches (drag page into different batch)
- **Split batch** — divide a batch at a page boundary into two batches
- **Merge batches** — combine two batches into one

All operations are metadata-only — no file moves. Implemented as updates to `scanning_batch_documents.order` and `batch_id` foreign keys.

**Audit trail:** Every virtual restack/rebundle operation is logged in `audit_logs` with operator, timestamp, and before/after state.

---

## Implementation Order (6-Month Roadmap)

```
Month 1-2: P0 (table stakes)
  Week 1-2:  Scan Agent skeleton (Go binary, local REST, TWAIN/WIA)
  Week 3-4:  Quality pipeline (local blur/skew/glare detection)
  Week 5-6:  ISIS driver support + scan profile sync
  Week 7-8:  Quality threshold config + rescan queue UI

Month 3-4: P1 (competitive parity)
  Week 9-10:  Barcode generation + scan-time barcode reading
  Week 11-12: Dedup pipeline (hash + perceptual hash)
  Week 13-14: Exception routing engine + operator exception queue
  Week 15-16: Supervisor dashboard v1 (live ops + operator KPIs)

Month 5-6: P2 (differentiation)
  Week 17-18: Camera capture mode + perspective correction
  Week 19-20: Multi-image stitching UI + OpenCV pipeline
  Week 21-22: Foot pedal / hotkey configuration
  Week 23-24: Virtual rebundling UI + adaptive deskewing
```

---

## What Makes dArchiva the Only Choice

After shipping P0+P1, dArchiva's unique position vs. competitors:

| Competitor | Their Weakness | Our Advantage |
|-----------|---------------|---------------|
| Kofax/Tungsten | Complex, expensive, Windows-only thick client | Web-first, multi-platform, SaaS |
| Kodak Alaris Capture Pro | No document management — capture only | Full DMS + capture in one platform |
| Hyland OnBase | On-premise only, high integration cost | Cloud-native, API-first, open |
| DocuWare | Weak scanning hardware integration | Native scanner client, ISIS support |
| Generic BPO (DataBank) | No self-service — must use their team | Self-service + BPO mode in same platform |

**Unique combination no competitor offers:**
1. Full document management + bulk scanning orchestration in one platform
2. Multi-site distributed scanning with offline-capable desktop agent
3. Automated QC pipeline with configurable thresholds (not manual spot-checks)
4. Supervisor analytics built-in (not a third-party add-on)
5. Camera capture + stitching for non-standard document sizes
6. Open API for integration with any existing workflow
