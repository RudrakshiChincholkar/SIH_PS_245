import logging
from typing import Tuple, Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings

logger = logging.getLogger(__name__)

# Create SQLAlchemy engine with connection pool pre-ping
# Connect timeout is passed via connect_args for psycopg2
engine = create_engine(
    settings.sync_database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={
        "connect_timeout": int(settings.DB_CHECK_TIMEOUT_SECONDS)
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session and ensures cleanup.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connectivity(custom_engine=None) -> Tuple[bool, str]:
    """
    Performs a real, lightweight connectivity check against PostgreSQL by executing 'SELECT 1'.
    
    Returns:
        (True, message) if connection succeeds.
        (False, sanitized_error_message) if connection fails.
    
    Security note:
        Error messages are sanitized to prevent credential/password leakage.
    """
    target_engine = custom_engine or engine
    try:
        with target_engine.connect() as conn:
            # Execute simple ping query
            result = conn.execute(text("SELECT 1")).scalar()
            if result == 1:
                return True, "PostgreSQL connection responsive"
            return False, "Unexpected ping response from database"
    except SQLAlchemyError as exc:
        # Sanitize message: strip any password from the error string if present
        raw_msg = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
        if settings.DB_PASSWORD and settings.DB_PASSWORD in raw_msg:
            sanitized_msg = raw_msg.replace(settings.DB_PASSWORD, "********")
        else:
            sanitized_msg = raw_msg
        logger.warning(f"Database health check failed: {sanitized_msg}")
        return False, f"Database connectivity error: {sanitized_msg}"
    except Exception as exc:
        logger.error(f"Unexpected error during database health check: {exc}")
        return False, "Database connectivity error: connection failed"


def get_db_health() -> Tuple[bool, str]:
    """
    FastAPI dependency for database health check.
    Allows easy dependency injection in unit tests to simulate available/unavailable states.
    """
    return check_database_connectivity()
