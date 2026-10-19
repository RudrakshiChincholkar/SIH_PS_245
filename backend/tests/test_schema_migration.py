from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

from app.models import VideoQualityAssessment
from scripts.migrate_video_quality_assessment import (
    _add_column_sql,
    migrate_video_quality_assessment,
    missing_video_quality_assessment_columns,
)
from tests.conftest import test_engine


def test_missing_column_ddl_matches_model_type_and_nullability():
    column = VideoQualityAssessment.__table__.c.avg_temporal_difference

    statement = _add_column_sql(column, postgresql.dialect())

    assert "ADD COLUMN IF NOT EXISTS avg_temporal_difference FLOAT NULL" in statement


def test_assessment_schema_migration_is_idempotent_and_matches_model():
    assert migrate_video_quality_assessment(test_engine) == []
    assert migrate_video_quality_assessment(test_engine) == []
    assert missing_video_quality_assessment_columns(test_engine) == []

    columns = {
        column["name"]: column
        for column in inspect(test_engine).get_columns("video_quality_assessments")
    }
    assert columns["avg_temporal_difference"]["nullable"] is True
