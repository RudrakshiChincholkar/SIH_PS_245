"""Idempotently create the additive frame-level occupancy results table."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import inspect

backend_root = str(Path(__file__).resolve().parents[1])
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.database import engine
from app.models import OccupancyFrame, VideoQualitySample

logger = logging.getLogger(__name__)


def migrate_occupancy_frames(target_engine=None) -> bool:
    """Create additive quality-sample and occupancy-frame tables if absent."""
    target_engine = target_engine or engine
    tables = (VideoQualitySample.__table__, OccupancyFrame.__table__)
    existed = all(inspect(target_engine).has_table(table.name) for table in tables)
    for table in tables:
        table.create(bind=target_engine, checkfirst=True)
    return not existed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check the table without changing the database")
    parser.add_argument(
        "--test-database",
        action="store_true",
        help="target the isolated TEST_DATABASE_URL instead of the application database",
    )
    args = parser.parse_args()
    target_engine = engine
    if args.test_database:
        from sqlalchemy import create_engine

        from app.config import settings

        target_engine = create_engine(settings.test_sync_database_url, pool_pre_ping=True)

    inspector = inspect(target_engine)
    required_tables = (VideoQualitySample.__tablename__, OccupancyFrame.__tablename__)
    missing_tables = [name for name in required_tables if not inspector.has_table(name)]
    if args.check:
        if missing_tables:
            raise SystemExit("Missing tables: " + ", ".join(missing_tables))
        logger.info("Part 4 frame-result schemas are present.")
        return
    created = migrate_occupancy_frames(target_engine)
    logger.info("Part 4 result tables %s.", "created" if created else "already exist")
    if args.test_database:
        target_engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
