# Architecture & Design Overview — SIH 2026 PS 245

## 1. Project Background
Government-funded skill development training centres (under NSDC, PMKVY, DDU-GKY, etc.) rely on the **Aadhaar Enabled Biometric Attendance System (AEBAS)** for tracking candidate attendance. However, training centres face discrepancies such as:
- **Proxy attendance / "punch and leave"**: Candidates punch in during morning hours but do not attend classes.
- **Inflated billing**: Ghost attendance submitted for funding claims without physical presence.

**Goal**: Build a privacy-preserving system that continuously verifies classroom physical occupancy using CCTV feeds and compares it with official AEBAS biometric attendance records.

---

## 2. High-Level Architecture

```
+-------------------------------------------------------------------------+
|                              PRESENTATION                               |
|              React + Vite Web Dashboard (Monitoring & Alerts)           |
+------------------------------------+------------------------------------+
                                     | HTTP / REST
+------------------------------------+------------------------------------+
|                               BACKEND                                   |
|                FastAPI ASGI Application (Python 3.10+)                  |
|                                                                         |
|  - Health & Diagnostics (/api/health, /api/health/db)                   |
|  - Aggregation & Discrepancy Engine (Future Part)                       |
|  - AEBAS Ingestion & Verification APIs (Future Part)                    |
+-------------------+---------------------------------+-------------------+
                    |                                 |
+-------------------+---------------+   +-------------+-------------------+
|             DATABASE              |   |       COMPUTER VISION (FUTURE)  |
|  PostgreSQL 14+                   |   |  - Pretrained YOLO Person Detector|
|  - Attendance records             |   |  - Camera Quality Validator     |
|  - 5-minute occupancy aggregates  |   |  - 5-Min Temporal Aggregator    |
|  - Discrepancy logs & alerts      |   |  - Privacy Box / Head Count Only|
+-----------------------------------+   +---------------------------------+
```

---

## 3. Privacy-First Principles
1. **No Facial Recognition**: The system counts bodies/heads using general object detection (YOLO). No individual facial embeddings or identities are captured from the camera feed.
2. **On-Premise / Edge Video Processing**: Video streams are processed locally; raw CCTV video footage is never uploaded to external unvetted servers.
3. **Data Anonymization**: Occupancy data is aggregated into 5-minute statistical windows (mean headcount, confidence) before comparison with AEBAS.

---

## 4. Part 1 Foundation Scope
In Part 1, the core foundation is established:
- **FastAPI backend** with modular configuration (`config.py`), database layer (`database.py`), and routes (`main.py`).
- **PostgreSQL connectivity** using SQLAlchemy with a dedicated least-privilege user `sih_user`.
- **Health monitoring**:
  - `GET /api/health`: General application liveness probe.
  - `GET /api/health/db`: Active PostgreSQL ping probe (`SELECT 1`).
- **React 18 + Vite frontend**:
  - Live status polling and connection diagnostic display.
  - Environment-based base URL configuration via `VITE_API_BASE_URL`.
- **Automated test suite**:
  - Unit tests with dependency injection for decoupled testing.
  - Integration tests for verifying real PostgreSQL instances.

---

## 5. Part 2 Input Ingestion Architecture

Part 2 introduces the secure multi-modal input ingestion layer:

```
[ CCTV Video (.mp4, .avi, .mov) ]  -->  Chunked Streaming (<= 200MB) & Magic Bytes Check  -->  backend/data/videos/<uuid>.<ext>
                                                                                                        |
                                                                                                        v
[ AEBAS Attendance CSV ]           -->  Full Pre-Validation (IST -> UTC) & All-or-Nothing  -->  attendance_records
                                                                                                        |
                                                                                                        v
[ Batch Schedule CSV ]             -->  Full Pre-Validation (Daytime) & Upsert Logic      -->  schedule_records
                                                                                                        |
                                                                                                        v
                                                                                                  uploads (Master Registry)
```

### Database Entity Relationships:
- **`uploads`**: Master registry storing `id` (UUID), `upload_type`, `original_filename`, `file_size_bytes`, `status` (`VALIDATED`, `REJECTED`), `row_count`, `error_message`, `created_at`.
- **`video_metadata`**: 1-to-1 with `uploads`. Stores `batch_id`, `classroom_id`, `recording_date_time`, `file_format`. Unique on `(batch_id, classroom_id, recording_date_time)`.
- **`attendance_records`**: Many-to-1 with `uploads`. Stores `batch_id`, `person_ref`, `punch_in` (TIMESTAMPTZ UTC), `punch_out` (TIMESTAMPTZ UTC). Unique on `(batch_id, person_ref, punch_in)`.
- **`schedule_records`**: Many-to-1 with `uploads`. Stores `batch_id`, `classroom_id`, `class_date`, `start_time`, `end_time`, `enrolled_count`. Unique on `(batch_id, classroom_id, class_date, start_time)`.
- **`video_quality_assessments`**: 1-to-1 with `uploads`. Stores processing status, overall quality (`USABLE` / `DEGRADED` / `UNUSABLE`), metadata, sample counts, decode ratio, blur/luminance scores, JSON quality flags, diagnostics, and completion time. Repeat analysis updates the same row.
- **`video_quality_samples`**: Many-to-1 with `uploads`. Stores the exact timestamp and per-frame Part 3 usability result so Part 4 can reuse the quality pipeline's sampled frames. Unique on `(upload_id, sample_index)`.
- **`occupancy_frames`**: Many-to-1 with `uploads`. Stores one sampled-frame result with timestamp, status, nullable person count, confidence summary, person boxes, quality flags, and optional annotated-evidence path. Unique on `(upload_id, sample_index)`; repeat processing replaces the frame result set transactionally.

---

## 6. Part 3 Video Quality Assessment

Part 3 adds an incremental decoder (`backend/app/video_processor.py`). The file path is resolved from the upload record and must remain inside the configured upload directory; clients cannot supply a filesystem path.

OpenCV reads frames sequentially (bounded memory), samples on a time grid (default 10 seconds), and computes Laplacian variance, mean grayscale luminance, and mean absolute difference between consecutive samples on a 320×180 grayscale canvas. Heuristics are preliminary and content-dependent.

Safety rule: failed, dark, blurred, frozen, or unreadable footage is missing visual evidence. It is never occupancy = 0.

## 7. Part 4 Frame-Level Person Counts

Part 4 runs Ultralytics YOLOv8n COCO person class only (`classes=[0]`) with CPU inference. The registered video path is reused and timestamps follow the Part 3 interval. Per-frame quality checks prevent unusable samples from entering the detector. There is no face recognition, identity tracking, five-minute aggregation, expected attendance calculation, discrepancy logic, or alerting in this part.
