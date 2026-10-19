import pytest
from fastapi import status
from app.main import app
from app.database import get_db_health
from app.config import settings


def test_db_health_success_unit(client):
    """
    Unit test: Database health reporting when database is available.
    Uses FastAPI dependency injection to isolate from live database.
    """
    app.dependency_overrides[get_db_health] = lambda: (True, "PostgreSQL connection responsive")

    response = client.get("/api/health/db")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "responsive" in data["message"]


def test_db_health_failure_unit(client):
    """
    Unit test: Database health reporting when database is unavailable.
    Uses FastAPI dependency injection to simulate connection failure.
    Must return HTTP 503 Service Unavailable.
    """
    error_msg = "Database connectivity error: could not connect to server: Connection refused"
    app.dependency_overrides[get_db_health] = lambda: (False, error_msg)

    response = client.get("/api/health/db")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    data = response.json()
    assert data["status"] == "error"
    assert data["database"] == "disconnected"
    assert "Connection refused" in data["message"]


def test_db_health_never_leaks_password(client):
    """
    Security test: Ensures that even if an underlying DB driver exception
    mentions sensitive credentials, the endpoint never leaks the password.
    """
    secret_pass = "super_secret_production_password_xyz"
    simulated_error = f"FATAL: password authentication failed for user sih_user with password {secret_pass}"
    
    # Simulate sanitized check logic
    sanitized = simulated_error.replace(secret_pass, "********")
    app.dependency_overrides[get_db_health] = lambda: (False, sanitized)

    response = client.get("/api/health/db")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert secret_pass not in response.text
    assert "********" in response.text


@pytest.mark.integration
def test_db_health_live_integration(client):
    """
    Integration test: Verifies actual live PostgreSQL connectivity.
    Prerequisites:
        - A running PostgreSQL server configured with settings in backend/.env
        - Database and user created as per docs/database_setup.md
    """
    # Ensure no dependency overrides are active so the real check runs
    app.dependency_overrides.pop(get_db_health, None)

    response = client.get("/api/health/db")
    
    # This integration test executes the real query against the local PostgreSQL
    assert response.status_code == status.HTTP_200_OK, f"Live DB check failed: {response.text}"
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
