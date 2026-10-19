# AI-based Attendance Monitoring System
### Smart India Hackathon 2026 — Problem Statement 245

Privacy-preserving automated attendance verification for government-funded skill-development training centres. Compares classroom physical occupancy estimated from CCTV with biometric attendance records from AEBAS to detect proxy attendance, ghost beneficiaries, and discrepancy patterns.

> **Current Implementation Phase**: **Part 1 — Project Foundation & Environment Setup**.  
> Computer-vision pipelines (YOLO, PyTorch, OpenCV) and attendance business logic will be implemented in subsequent phases.

---

## 1. Architecture Overview

```
sih-attendance-monitoring/
├── backend/                       # Python FastAPI backend service
│   ├── app/
│   │   ├── config.py              # Environment configuration & validation
│   │   ├── database.py            # PostgreSQL SQLAlchemy connectivity & pings
│   │   └── main.py                # FastAPI routes, CORS, and health checks
│   ├── tests/
│   │   ├── conftest.py            # Pytest test fixtures
│   │   ├── test_health.py         # App health tests (no DB required)
│   │   └── test_db_health.py      # DB unit & integration tests
│   ├── requirements.txt           # Python dependencies
│   ├── pytest.ini                 # Pytest test suite configuration
│   └── .env.example               # Backend environment template
├── frontend/                      # React with Vite frontend application
│   ├── src/
│   │   ├── App.jsx                # Landing page with real-time status diagnostics
│   │   ├── App.css                # Component styles
│   │   ├── main.jsx               # React entrypoint
│   │   └── index.css              # Global styles
│   ├── package.json               # Node.js dependencies & scripts
│   ├── vite.config.js             # Vite configuration
│   └── .env.example               # Frontend environment template
├── docs/                          # Technical documentation
│   ├── architecture.md            # System design & future pipeline roadmap
│   ├── database_setup.md          # PostgreSQL setup & user guide
│   └── api_specification.md       # API endpoint details & response schemas
├── .gitignore                     # Git ignore rules (secrets, venv, node_modules)
└── README.md                      # Project documentation (this file)
```

---

## 2. Prerequisites & Verified Versions

| Tool | Minimum Version | Tested & Verified Version |
| :--- | :--- | :--- |
| **Linux OS** | Ubuntu 20.04+ | Ubuntu 22.04 LTS (x86_64) |
| **Python** | 3.10+ | Python 3.10.12 |
| **Node.js** | 18+ | Node.js v20.20.2 |
| **npm** | 9+ | npm 10.8.2 |
| **PostgreSQL** | 14+ | PostgreSQL 14.24 |

---

## 3. Database Setup (PostgreSQL)

The application uses a **dedicated, least-privilege user** (`sih_user`) rather than the postgres superuser.

```bash
# 1. Verify PostgreSQL service is running
sudo systemctl status postgresql

# 2. Open PostgreSQL admin shell
sudo -u postgres psql

# 3. In the psql prompt, execute:
CREATE ROLE sih_user WITH LOGIN PASSWORD 'sih_secure_pass_2026';
CREATE DATABASE sih_attendance OWNER sih_user;
GRANT ALL PRIVILEGES ON DATABASE sih_attendance TO sih_user;
\c sih_attendance
GRANT ALL ON SCHEMA public TO sih_user;
\q

# 4. Verify connectivity
PGPASSWORD='sih_secure_pass_2026' psql -h localhost -U sih_user -d sih_attendance -c "SELECT current_user, current_database();"
```

For complete database configuration details, see [docs/database_setup.md](docs/database_setup.md).

---

## 4. Backend Setup & Startup

### Step 1: Create and activate a Python virtual environment
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
```

### Step 2: Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Configure environment variables
```bash
cp .env.example .env
```
Ensure your `backend/.env` has the correct settings:
```env
PROJECT_NAME="AI-based Attendance Monitoring System"
ENVIRONMENT="development"
DEBUG=true
HOST="0.0.0.0"
PORT=8000
CORS_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173"]'
DB_HOST="localhost"
DB_PORT=5432
DB_USER="sih_user"
DB_PASSWORD="sih_secure_pass_2026"
DB_NAME="sih_attendance"
```

### Step 4: Run the FastAPI backend server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
The backend will be available at:
- **Base URL**: `http://localhost:8000`
- **Interactive OpenAPI Documentation**: `http://localhost:8000/docs`
- **Health Check**: `http://localhost:8000/api/health`
- **Database Health Check**: `http://localhost:8000/api/health/db`

---

## 5. Frontend Setup & Startup

### Step 1: Install Node.js dependencies
```bash
cd frontend
npm install
```

### Step 2: Configure environment variables
```bash
cp .env.example .env
```
Ensure `frontend/.env` contains:
```env
VITE_API_BASE_URL=http://localhost:8000
```

### Step 3: Start the Vite development server
```bash
npm run dev
```
The frontend landing page will be available at `http://localhost:5173`.

### Step 4: Production build verification
To test building the frontend for production:
```bash
npm run build
```

---

## 6. Environment Variables Reference

### Backend (`backend/.env`)
| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `PROJECT_NAME` | Name of the project | `AI-based Attendance Monitoring System` |
| `ENVIRONMENT` | Runtime environment (`development` / `production`) | `development` |
| `DEBUG` | Enable debug logs | `true` |
| `HOST` | Server bind IP address | `0.0.0.0` |
| `PORT` | Server listen port | `8000` |
| `CORS_ORIGINS` | JSON list or comma-separated origins for CORS | `["http://localhost:5173","http://127.0.0.1:5173"]` |
| `DB_HOST` | PostgreSQL host | `localhost` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_USER` | Least-privilege PostgreSQL username | `sih_user` |
| `DB_PASSWORD` | PostgreSQL password | `sih_secure_pass_2026` |
| `DB_NAME` | PostgreSQL database name | `sih_attendance` |
| `DATABASE_URL` | Optional full connection string override | *(Computed automatically)* |

### Frontend (`frontend/.env`)
| Variable | Description | Default |
| :--- | :--- | :--- |
| `VITE_API_BASE_URL` | Base URL of FastAPI backend | `http://localhost:8000` |

---

## 7. API Endpoints & Example Responses

### `GET /api/health`
Liveness probe checking FastAPI backend operation. Runs completely independently of PostgreSQL.

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
Readiness probe verifying live PostgreSQL connectivity via lightweight `SELECT 1`.

**Response when database is connected (HTTP 200 OK):**
```json
{
  "status": "ok",
  "database": "connected",
  "message": "PostgreSQL connection responsive"
}
```

**Response when database is unreachable (HTTP 503 Service Unavailable):**
```json
{
  "status": "error",
  "database": "disconnected",
  "message": "Database connectivity error: connection refused"
}
```

---

## 8. Running Automated Tests

Activate the virtual environment before running tests:
```bash
cd backend
source venv/bin/activate
```

### 1. Run Unit Tests Only (No Database Required)
Unit tests use FastAPI dependency overrides to test both success and failure states without needing a running PostgreSQL instance:
```bash
pytest -v -m "not integration"
```

### 2. Run Integration Tests (Requires Running PostgreSQL)
Tests live query execution against the configured database:
```bash
pytest -v -m "integration"
```

### 3. Run the Entire Test Suite
```bash
pytest -v
```

---

## 9. Troubleshooting & Common Errors

### Error: `Failed to fetch` on frontend landing page
- **Symptom**: Frontend shows `Disconnected` badge.
- **Cause**: Backend server is not running or `VITE_API_BASE_URL` is pointing to the wrong port.
- **Fix**: Verify backend is running on `http://localhost:8000` with `curl http://localhost:8000/api/health`.

### Error: `CORS header 'Access-Control-Allow-Origin' missing`
- **Symptom**: Browser blocks requests from `http://localhost:5173`.
- **Cause**: Frontend origin is not listed in `backend/.env` under `CORS_ORIGINS`.
- **Fix**: Add `"http://localhost:5173"` to `CORS_ORIGINS` in `backend/.env` and restart the backend.

### Error: `could not connect to server: Connection refused` on `/api/health/db`
- **Symptom**: Backend `/api/health` returns 200 OK, but `/api/health/db` returns 503.
- **Cause**: PostgreSQL service is stopped or listening on another port.
- **Fix**: Run `sudo systemctl start postgresql` and check `pg_isready`.

### Error: `FATAL: password authentication failed for user "sih_user"`
- **Symptom**: `/api/health/db` returns 503 with authentication error.
- **Cause**: Password in `backend/.env` does not match the PostgreSQL role password.
- **Fix**: Update `DB_PASSWORD` in `backend/.env` or reset password in PostgreSQL via:
  ```sql
  ALTER ROLE sih_user WITH PASSWORD 'sih_secure_pass_2026';
  ```
