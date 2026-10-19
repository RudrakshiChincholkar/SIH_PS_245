"""Safely add missing nullable columns to the video-quality assessment table."""

from __future__ import annotations

import logging
import argparse
import sys
from pathlib import Path
from typing import List

from sqlalchemy import Engine, inspect, text

backend_root = str(Path(__file__).resolve().parents[1])
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.database import engine
from app.models import VideoQualityAssessment

logger = logging.getLogger(__name__)


def _add_column_sql(column, dialect) -> str:
    if not column.nullable:
        raise RuntimeError(
            f"Refusing to add missing non-nullable column {column.name!r} "
            "without a data migration/default strategy."
        )
    preparer = dialect.identifier_preparer
    table_name = preparer.quote(VideoQualityAssessment.__table__.name)
    column_name = preparer.quote(column.name)
    column_type = column.type.compile(dialect=dialect)
    return (
        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS "
        f"{column_name} {column_type} NULL"
    )


def migrate_video_quality_assessment(target_engine: Engine = engine) -> List[str]:
    """Apply safe additions for any missing nullable model columns, preserving rows."""
    model_table = VideoQualityAssessment.__table__
    added_columns: List[str] = []

    with target_engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table(model_table.name):
            raise RuntimeError(
                f"Table {model_table.name!r} does not exist; initialize the application schema first."
            )
        existing_names = {
            column["name"] for column in inspector.get_columns(model_table.name)
        }
        missing_columns = [
            column for column in model_table.columns if column.name not in existing_names
        ]

        for column in missing_columns:
            statement = _add_column_sql(column, connection.dialect)
            connection.execute(text(statement))
            added_columns.append(column.name)

    return added_columns


def missing_video_quality_assessment_columns(target_engine: Engine = engine) -> List[str]:
    model_table = VideoQualityAssessment.__table__
    inspector = inspect(target_engine)
    if not inspector.has_table(model_table.name):
        raise RuntimeError(f"Table {model_table.name!r} does not exist.")
    existing_names = {
        column["name"] for column in inspector.get_columns(model_table.name)
    }
    return [
        column.name
        for column in model_table.columns
        if column.name not in existing_names
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report missing model columns without applying changes",
    )
    args = parser.parse_args()

    if args.check:
        missing = missing_video_quality_assessment_columns()
        if missing:
            raise SystemExit("Missing video-quality assessment columns: " + ", ".join(missing))
        logger.info("Video-quality assessment schema matches the model.")
        return

    added_columns = migrate_video_quality_assessment()
    if added_columns:
        logger.info(
            "Added missing video-quality assessment columns: %s",
            ", ".join(added_columns),
        )
    else:
        logger.info("Video-quality assessment schema is already current.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
