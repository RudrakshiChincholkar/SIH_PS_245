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
