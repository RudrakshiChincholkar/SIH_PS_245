import os
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import get_db, get_db_health, check_database_connectivity
from app.models import Base, Upload, VideoMetadata, AttendanceRecord, ScheduleRecord
from app.main import app

# Create isolated test engine using the Git-ignored configured test database URL
# (Never prints credentials in logs)
test_engine = create_engine(
    settings.test_sync_database_url,
    pool_pre_ping=True
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """
    Session fixture that initializes all tables in the isolated test database.
    """
    Base.metadata.create_all(bind=test_engine)
    yield


@pytest.fixture
def db_session():
    """
    Provides a clean database session connected to the isolated test database.
    Truncates test tables after each test to ensure test isolation.
    """
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        # Clean up test data
        with test_engine.begin() as conn:
            conn.execute(text(
                "TRUNCATE TABLE occupancy_frames, video_quality_samples, video_quality_assessments, schedule_records, "
                "attendance_records, video_metadata, uploads CASCADE;"
            ))


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch, tmp_path):
    """
    Redirects video and CSV upload directories to a temporary folder during tests.
    Also ensures FastAPI uses the isolated test database for all requests.
    """
    test_upload_dir = tmp_path / "test_data"
    test_upload_dir.mkdir(parents=True, exist_ok=True)
    (test_upload_dir / "videos").mkdir(parents=True, exist_ok=True)
    (test_upload_dir / "csvs").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(test_upload_dir))

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(isolate_test_environment):
    """
    FastAPI TestClient fixture configured to use the isolated test database.
    """
    with TestClient(app) as test_client:
        yield test_client
