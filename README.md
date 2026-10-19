# AI-based Attendance Monitoring System
### Smart India Hackathon 2026 — Problem Statement 245

Privacy-preserving automated attendance verification for government-funded skill-development training centres. Compares classroom physical occupancy estimated from CCTV with biometric attendance records from AEBAS to detect proxy attendance, ghost beneficiaries, and discrepancy patterns.

> **Current Implementation Phase**: **Part 2 — Input Ingestion**.  
> Video streaming & magic-byte validation, mock AEBAS attendance CSV import, batch schedule CSV import, and upload registry are fully operational. Computer-vision pipelines (YOLO, person counting) belong to subsequent phases.

---

## 1. Architecture Overview

```
sih-attendance-monitoring/
├── backend/                       # Python FastAPI backend service
│   ├── app/
│   │   ├── config.py              # Environment configuration & validation
│   │   ├── database.py            # PostgreSQL SQLAlchemy engine & connectivity checks
│   │   ├── models.py              # Upload, VideoMetadata, AttendanceRecord, ScheduleRecord
│   │   ├── schemas.py             # Pydantic schemas (no server path leakage)
│   │   ├── validators.py          # Chunked video streaming, magic bytes & CSV validators
│   │   ├── routes/
│   │   │   └── ingest.py          # Ingestion endpoints (/api/ingest/*)
│   │   └── main.py                # FastAPI routes, CORS, and health checks
│   ├── tests/
│   │   ├── conftest.py            # Pytest test fixtures (isolated test database)
│   │   ├── test_health.py         # App health tests
│   │   ├── test_db_health.py      # DB unit & integration tests
│   │   ├── test_ingest_video.py   # Streaming, magic bytes & video upload tests
│   │   ├── test_ingest_attendance.py # All-or-nothing CSV, IST->UTC, & duplicate tests
│   │   ├── test_ingest_schedule.py   # Schedule validation & upsert tests
│   │   └── test_ingest_uploads.py    # Registry listing & template download tests
│   ├── requirements.txt           # Pinned Python dependencies
│   ├── pytest.ini                 # Pytest test suite configuration
│   └── .env.example               # Backend environment template
├── frontend/                      # React with Vite frontend application
│   ├── src/
│   │   ├── App.jsx                # Ingestion hub & system diagnostics
│   │   ├── App.css                # Component styles
│   │   ├── main.jsx               # React entrypoint
│   │   └── index.css              # Global styles
│   ├── package.json               # Node.js dependencies & scripts
│   ├── vite.config.js             # Vite configuration (port 5173)
│   └── .env.example               # Frontend environment template
├── docs/                          # Technical documentation
│   ├── architecture.md            # System design & future pipeline roadmap
│   ├── database_setup.md          # PostgreSQL setup & test database guide
│   └── api_specification.md       # API endpoint details & response schemas
├── .gitignore                     # Git ignore rules (secrets, venv, node_modules, data/)
└── README.md                      # Project documentation (this file)
```

---

## 2. Ingestion Specifications & Rules

### A. Recorded CCTV Video Files
- **Supported Formats**: `.mp4`, `.avi`, `.mov`.
- **Upload Limit**: 200 MB maximum (configured via `MAX_VIDEO_SIZE_MB`).
- **Streaming Protection**: Enforces chunked streaming (1 MB buffer); unlinks file and returns HTTP 413 if limit exceeded. Never loads entire video into RAM.
- **Media Validation**: Verifies container magic bytes (`ftyp` for MP4/MOV, `RIFF...AVI ` for AVI) on first chunk.
- **Storage Location**: Stored as `<uuid4>.<ext>` inside `backend/data/videos/` (strictly outside frontend and ignored in Git).
- **Duplicate Prevention**: Rejects duplicate slots for `(batch_id, classroom_id, recording_date_time)` with HTTP 409 Conflict.
- **Path Sanitization**: Absolute filesystem paths are never returned in API responses.

### B. Mock AEBAS Attendance CSV
- **Required Columns**: `batch_id,person_ref,punch_in,punch_out`
- **Validation Rules**:
  - Non-empty `batch_id` and `person_ref`.
  - Valid timestamps parsed as IST (`UTC+05:30`) if naive and stored as UTC in PostgreSQL (`TIMESTAMPTZ`).
  - `punch_out` is optional, but if provided, must be `punch_out >= punch_in`.
  - Intra-file duplicate punches for `(batch_id, person_ref, punch_in)` are flagged as errors.
- **All-or-Nothing Atomicity**: If any row fails, **zero** attendance records are inserted. A `REJECTED` upload audit record is persisted in PostgreSQL with row-level error details.

### C. Batch Schedule CSV
- **Required Columns**: `batch_id,classroom_id,class_date,start_time,end_time,enrolled_count`
- **Validation Rules**:
  - Valid dates (`YYYY-MM-DD`) and times (`HH:MM`).
  - Same-calendar-day class constraint: `end_time > start_time`.
  - Non-negative `enrolled_count >= 0`.
  - Conflicting duplicate entries within the same CSV are rejected.
- **Deterministic Upsert**: Uploads matching previously registered slots update `end_time`, `enrolled_count`, and `upload_id` for idempotent revisions.

---

## 3. Database Setup (PostgreSQL)

The application uses a **dedicated, least-privilege user** (`sih_user`) rather than the postgres superuser.

```bash
# 1. Connect to PostgreSQL admin
sudo -u postgres psql

# 2. In psql, run:
CREATE ROLE sih_user WITH LOGIN PASSWORD 'sih_secure_pass_2026';
CREATE DATABASE sih_attendance OWNER sih_user;
CREATE DATABASE sih_attendance_test OWNER sih_user;
GRANT ALL PRIVILEGES ON DATABASE sih_attendance TO sih_user;
GRANT ALL PRIVILEGES ON DATABASE sih_attendance_test TO sih_user;
\c sih_attendance
GRANT ALL ON SCHEMA public TO sih_user;
\c sih_attendance_test
GRANT ALL ON SCHEMA public TO sih_user;
\q
```

---

## 4. Quickstart

### Backend Setup & Startup
```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Start the FastAPI server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend Setup & Startup
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```
Open your browser at `http://localhost:5173`.

---

## 5. Automated Tests

All tests run against the isolated test database `sih_attendance_test` (configured in `backend/.env`, never printing credentials):

```bash
cd backend
venv/bin/pytest -v
```

### Test Suite Highlights (25 Tests):
- **Health diagnostics**: Verifies backend and database health checks.
- **Video ingestion**: Validates chunked streaming, 413 cutoff, magic byte checks, 409 duplicates, and file cleanup.
- **Attendance ingestion**: Tests all-or-nothing rollback, rejection audit persistence, and IST-to-UTC conversion (`2026-10-19 09:30:00 IST` == `2026-10-19 04:00:00 UTC`).
- **Schedule ingestion**: Tests same-day constraints, conflicting row rejection, and deterministic upsert.
- **Upload registry**: Tests pagination, filters, and CSV template downloads.
