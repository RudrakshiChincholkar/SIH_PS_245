import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    """
    TestClient fixture for executing API requests in tests.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    """
    Ensures that FastAPI dependency overrides are cleared after each test.
    """
    yield
    app.dependency_overrides.clear()
