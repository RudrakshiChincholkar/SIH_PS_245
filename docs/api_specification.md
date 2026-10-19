# API Specification — AI-based Attendance Monitoring System

Base URL: `http://localhost:8000`

---

## 1. Root Endpoint

### `GET /`
Returns root application metadata and discovery links.

**Request:**
- Method: `GET`
- Path: `/`
- Headers: None

**Response (HTTP 200 OK):**
```json
{
  "message": "Welcome to AI-based Attendance Monitoring System",
  "environment": "development",
  "docs_url": "/docs",
  "health_check": "/api/health",
  "database_health_check": "/api/health/db"
}
```

---

## 2. Application Health Check

### `GET /api/health`
Liveness probe checking whether the FastAPI application server is alive and responding. This endpoint operates independently of database connectivity.

**Request:**
- Method: `GET`
- Path: `/api/health`
- Headers: None

**Response (HTTP 200 OK):**
```json
{
  "status": "ok",
  "service": "sih-attendance-backend",
  "environment": "development",
  "version": "1.0.0"
}
```

---

## 3. Database Health Check

### `GET /api/health/db`
Active readiness probe that tests database connectivity by executing a lightweight `SELECT 1` query against PostgreSQL.

**Request:**
- Method: `GET`
- Path: `/api/health/db`
- Headers: None

**Response — Success (HTTP 200 OK):**
```json
{
  "status": "ok",
  "database": "connected",
  "message": "PostgreSQL connection responsive"
}
```

**Response — Database Failure (HTTP 503 Service Unavailable):**
```json
{
  "status": "error",
  "database": "disconnected",
  "message": "Database connectivity error: could not connect to server: Connection refused"
}
```

> **Security Note**: All error messages from this endpoint are sanitized so that database passwords and sensitive connection parameters are never returned in responses.
