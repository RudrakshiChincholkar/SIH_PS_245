# API Specification — AI-based Attendance Monitoring System

Base URL: `http://localhost:8000`

---

## 1. System Health Diagnostics (Part 1)

### `GET /api/health`
Liveness probe checking whether the FastAPI application server is alive and responding. Operates independently of database connectivity.

**Response (HTTP 200 OK):**
```json
{
  "status": "ok",
  "service": "sih-attendance-backend",
  "environment": "development",
  "version": "1.0.0"
}
```

### `GET /api/health/db`
Readiness probe verifying active PostgreSQL database connectivity via `SELECT 1`.

**Response (HTTP 200 OK):**
```json
{
  "status": "ok",
  "database": "connected",
  "message": "PostgreSQL connection responsive"
}
```

---

## 2. Input Ingestion Endpoints (Part 2)

### `POST /api/ingest/video`
Uploads and validates a recorded CCTV video file (.mp4, .avi, .mov).
- **Streaming**: Enforces chunked streaming with a 200 MB maximum limit; never loads the entire file into RAM.
- **Magic Byte Validation**: Validates container headers (`ftyp` for MP4/MOV, `RIFF...AVI ` for AVI).
- **Duplicate Prevention**: Rejects duplicate video slots for `(batch_id, classroom_id, recording_date_time)`.
- **Security**: Stores files as `<uuid4>.<ext>`. Absolute server paths are never exposed in responses.

**Request:** `multipart/form-data`
- `file`: Video file (`.mp4`, `.avi`, `.mov`)
- `batch_id`: String (e.g. `BATCH-2026-A1`)
- `classroom_id`: String (e.g. `ROOM-101`)
- `recording_date_time`: String (ISO 8601 or `YYYY-MM-DD HH:MM:SS`, parsed as IST if naive)

**Response (HTTP 201 Created):**
```json
{
  "message": "Video upload successfully validated and registered.",
  "upload": {
    "id": "c1f71a93-8b7c-473d-82d2-5a21db53b01a",
    "upload_type": "video",
    "original_filename": "classroom_cctv.mp4",
    "file_size_bytes": 15482910,
    "status": "VALIDATED",
    "row_count": 0,
    "error_message": null,
    "created_at": "2026-10-19T06:00:00Z"
  },
  "video_metadata": {
    "batch_id": "BATCH-2026-A1",
    "classroom_id": "ROOM-101",
    "recording_date_time": "2026-10-19T04:00:00Z",
    "file_format": "mp4"
  }
}
```

**Errors:**
- `HTTP 400 Bad Request`: Unsupported extension or blank parameters.
- `HTTP 409 Conflict`: Duplicate video submission for the same slot.
- `HTTP 413 Payload Too Large`: File exceeds configured maximum size limit (200 MB).
- `HTTP 415 Unsupported Media Type`: Corrupted header or invalid container magic bytes.

---

### `POST /api/ingest/attendance`
Uploads and validates mock AEBAS biometric attendance records.
- **Pre-Validation**: All rows are parsed before database insertion.
- **All-or-Nothing Atomicity**: Any row failure rejects the entire file (0 records inserted).
- **Rejection Audit**: The `REJECTED` upload status and error messages are saved in PostgreSQL for diagnostic auditing.

**Request:** `multipart/form-data`
- `file`: CSV file with header: `batch_id,person_ref,punch_in,punch_out`

**Sample CSV Content:**
```csv
batch_id,person_ref,punch_in,punch_out
BATCH-2026-A1,CAND-001,2026-10-19 09:00:00,2026-10-19 13:00:00
BATCH-2026-A1,CAND-002,2026-10-19 09:05:00,2026-10-19 13:02:00
BATCH-2026-A1,CAND-003,2026-10-19 09:12:00,
```

**Response (HTTP 201 Created):**
```json
{
  "message": "Successfully validated and imported 3 attendance records.",
  "upload": {
    "id": "9b2c3d4e-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
    "upload_type": "attendance_csv",
    "original_filename": "attendance.csv",
    "file_size_bytes": 182,
    "status": "VALIDATED",
    "row_count": 3,
    "error_message": null,
    "created_at": "2026-10-19T06:05:00Z"
  },
  "imported_records": 3
}
```

**Error Response (HTTP 422 Unprocessable Entity):**
```json
{
  "detail": "Attendance CSV validation failed.",
  "errors": [
    "Row 3: punch_out (2026-10-19 08:00:00) cannot be earlier than punch_in (2026-10-19 12:00:00)."
  ],
  "upload_id": "9b2c3d4e-5f6a-7b8c-9d0e-1f2a3b4c5d6e"
}
```

---

### `POST /api/ingest/schedule`
Uploads and validates batch training schedule records.
- **Constraints**: Enforces same-calendar-day class constraints (`end_time > start_time`) and non-negative `enrolled_count`.
- **Duplicate Handling**: Conflicting intra-file duplicates reject the CSV. Previous schedule slots uploaded in earlier files are deterministically upserted/updated.

**Request:** `multipart/form-data`
- `file`: CSV file with header: `batch_id,classroom_id,class_date,start_time,end_time,enrolled_count`

**Sample CSV Content:**
```csv
batch_id,classroom_id,class_date,start_time,end_time,enrolled_count
BATCH-2026-A1,ROOM-101,2026-10-19,09:00,13:00,30
BATCH-2026-A2,ROOM-101,2026-10-19,14:00,18:00,28
BATCH-2026-B1,ROOM-102,2026-10-19,09:30,13:30,25
```

**Response (HTTP 201 Created):**
```json
{
  "message": "Successfully processed 3 schedule records (3 inserted, 0 updated).",
  "upload": {
    "id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
    "upload_type": "schedule_csv",
    "original_filename": "schedule.csv",
    "file_size_bytes": 215,
    "status": "VALIDATED",
    "row_count": 3,
    "error_message": null,
    "created_at": "2026-10-19T06:10:00Z"
  },
  "inserted_records": 3,
  "updated_records": 0
}
```

---

### `GET /api/ingest/uploads`
Returns paginated list of previous uploads with validation status.

**Query Parameters:**
- `upload_type`: Optional string (`video`, `attendance_csv`, `schedule_csv`)
- `status`: Optional string (`VALIDATED`, `REJECTED`, `FAILED`)
- `limit`: Integer (default 50)
- `offset`: Integer (default 0)

---

### `GET /api/ingest/uploads/{upload_id}`
Returns metadata for a specific upload by UUID. Returns HTTP 404 if not found.

---

### `GET /api/ingest/templates/attendance` & `GET /api/ingest/templates/schedule`
Downloadable CSV template endpoints providing reference column headers and example rows.
