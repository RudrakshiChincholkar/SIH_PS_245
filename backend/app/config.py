import json
import os
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
