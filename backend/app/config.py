import json
import os
import math
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables or .env file.
    Validates configuration and ensures sensitive values are handled securely.
    """
    PROJECT_NAME: str = "AI-based Attendance Monitoring System"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Server binding
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS origins allowed to access the API
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # PostgreSQL Database settings
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "sih_user"
    DB_PASSWORD: str = ""
    DB_NAME: str = "sih_attendance"
    DATABASE_URL: Optional[str] = None

    # Database connectivity check timeout in seconds
    DB_CHECK_TIMEOUT_SECONDS: float = 3.0

    # Ingestion & Video upload settings
    MAX_VIDEO_SIZE_MB: int = 200
    ALLOWED_VIDEO_EXTENSIONS: List[str] = [".mp4", ".avi", ".mov"]
    UPLOAD_DIR: str = "data"

    # Part 3 video quality sampling (seconds). Bounds reject unbounded client values.
    VIDEO_SAMPLE_INTERVAL_SECONDS: float = 10.0
    VIDEO_SAMPLE_INTERVAL_MIN: float = 0.5
    VIDEO_SAMPLE_INTERVAL_MAX: float = 60.0
    VIDEO_QUALITY_BLUR_THRESHOLD: float = 100.0
    VIDEO_QUALITY_LOW_LIGHT_THRESHOLD: float = 40.0
    VIDEO_QUALITY_OVEREXPOSURE_THRESHOLD: float = 230.0
    VIDEO_QUALITY_NEAR_IDENTICAL_MAD_THRESHOLD: float = 1.0
    VIDEO_QUALITY_MIN_DECODE_SUCCESS_RATIO: float = 0.8
    VIDEO_QUALITY_BLACK_LUMINANCE_THRESHOLD: float = 8.0
    VIDEO_QUALITY_FROZEN_MIN_IDENTICAL_PAIRS: int = 3
    VIDEO_QUALITY_FROZEN_IDENTICAL_PAIR_RATIO: float = 0.85

    # Part 4 CPU-only COCO person detection (Ultralytics YOLOv8n).
    PERSON_DETECTOR_MODEL: str = "yolov8n.pt"
    PERSON_DETECTION_CONFIDENCE: float = 0.25
    PERSON_DETECTION_IOU: float = 0.45
    PERSON_DETECTION_DEVICE: str = "cpu"
    OCCUPANCY_EVIDENCE_ENABLED: bool = False
    OCCUPANCY_EVIDENCE_MAX_FRAMES: int = 20

    # Test Database settings (isolated database for automated tests)
    TEST_DB_NAME: Optional[str] = "sih_attendance_test"
    TEST_DATABASE_URL: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except Exception:
                    pass
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("ALLOWED_VIDEO_EXTENSIONS", mode="before")
    @classmethod
    def parse_allowed_extensions(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except Exception:
                    pass
            return [ext.strip().lower() for ext in value.split(",") if ext.strip()]
        return [ext.lower() for ext in value]

    @field_validator("PERSON_DETECTION_CONFIDENCE", "PERSON_DETECTION_IOU")
    @classmethod
    def validate_person_detection_threshold(cls, value):
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("Person detection thresholds must be between 0 and 1.")
        return value

    @field_validator("OCCUPANCY_EVIDENCE_MAX_FRAMES")
    @classmethod
    def validate_evidence_frame_limit(cls, value):
        if value < 0:
            raise ValueError("OCCUPANCY_EVIDENCE_MAX_FRAMES cannot be negative.")
        return value

    @property
    def base_dir(self) -> Path:
        """Returns the backend root directory."""
        return Path(__file__).resolve().parent.parent

    @property
    def video_upload_dir(self) -> Path:
        """Returns the dedicated directory for storing videos and ensures it exists."""
        upload_path = Path(self.UPLOAD_DIR)
        target = (upload_path if upload_path.is_absolute() else self.base_dir / upload_path) / "videos"
        target.mkdir(parents=True, exist_ok=True)
        return target

    @property
    def csv_upload_dir(self) -> Path:
        """Returns the dedicated directory for storing raw CSV archives and ensures it exists."""
        upload_path = Path(self.UPLOAD_DIR)
        target = (upload_path if upload_path.is_absolute() else self.base_dir / upload_path) / "csvs"
        target.mkdir(parents=True, exist_ok=True)
        return target

    @property
    def occupancy_evidence_dir(self) -> Path:
        upload_path = Path(self.UPLOAD_DIR)
        root = upload_path if upload_path.is_absolute() else self.base_dir / upload_path
        target = root / "occupancy-evidence"
        target.mkdir(parents=True, exist_ok=True)
        return target


    @property
    def test_sync_database_url(self) -> str:
        """
        Construct or return the test database URL for running isolated automated tests.
        Never print credentials in logs or commands.
        """
        if self.TEST_DATABASE_URL:
            return self.TEST_DATABASE_URL
        
        test_db = self.TEST_DB_NAME or f"{self.DB_NAME}_test"
        encoded_password = quote_plus(self.DB_PASSWORD) if self.DB_PASSWORD else ""
        user_part = f"{self.DB_USER}:{encoded_password}@" if self.DB_USER else ""
        return f"postgresql+psycopg2://{user_part}{self.DB_HOST}:{self.DB_PORT}/{test_db}"

    @property
    def sync_database_url(self) -> str:
        """
        Construct or return the SQLAlchemy synchronous PostgreSQL database URL.
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL
        
        encoded_password = quote_plus(self.DB_PASSWORD) if self.DB_PASSWORD else ""
        user_part = f"{self.DB_USER}:{encoded_password}@" if self.DB_USER else ""
        return f"postgresql+psycopg2://{user_part}{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    def get_sanitized_db_url(self) -> str:
        """
        Returns the database URL with the password masked, safe for logging or debugging.
        Never prints or exposes raw credentials.
        """
        url = self.sync_database_url
        if self.DB_PASSWORD and self.DB_PASSWORD in url:
            return url.replace(quote_plus(self.DB_PASSWORD), "********")
        return url


# Singleton instance
settings = Settings()
