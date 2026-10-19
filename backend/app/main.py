import logging
from typing import Tuple
from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import get_db_health

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("attendance_backend")

# Initialize FastAPI application
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API for AI-based Attendance Monitoring System (SIH 2026 PS 245)",
    version="1.0.0"
)

# Configure CORS
# In production, wildcard origin '*' is strictly rejected.
if settings.ENVIRONMENT == "production" and "*" in settings.CORS_ORIGINS:
    raise ValueError("Wildcard '*' CORS origin is not permitted in production environment.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/", tags=["Root"])
def read_root():
    """
    Root entrypoint providing basic service info and OpenAPI doc links.
    """
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "environment": settings.ENVIRONMENT,
        "docs_url": "/docs",
        "health_check": "/api/health",
        "database_health_check": "/api/health/db"
    }


@app.get("/api/health", tags=["Health"])
def health_check():
    """
    General backend health check.
    Returns HTTP 200 if the FastAPI application is alive and responding.
    Independent of PostgreSQL connectivity.
    """
    return {
        "status": "ok",
        "service": "sih-attendance-backend",
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0"
    }


@app.get("/api/health/db", tags=["Health"])
def database_health_check(db_status: Tuple[bool, str] = Depends(get_db_health)):
    """
    PostgreSQL connectivity health check.
    Executes a real lightweight ping (SELECT 1) against the configured PostgreSQL instance.
    
    Returns:
        HTTP 200 OK: when database responds successfully.
        HTTP 503 SERVICE UNAVAILABLE: when database is unreachable or query fails.
    """
    is_connected, message = db_status

    if not is_connected:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "database": "disconnected",
                "message": message
            }
        )

    return {
        "status": "ok",
        "database": "connected",
        "message": message
    }
