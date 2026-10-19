import io
from datetime import date, time
import pytest
from fastapi import status
from app.models import Upload, ScheduleRecord


def test_valid_schedule_csv_import(client, db_session):
    """
    Test uploading a valid batch schedule CSV file.
    Verifies 201 Created and database persistence.
    """
    csv_content = (
        "batch_id,classroom_id,class_date,start_time,end_time,enrolled_count\n"
        "BATCH-2026-A1,ROOM-101,2026-10-19,09:00,13:00,30\n"
        "BATCH-2026-A1,ROOM-101,2026-10-19,14:00,18:00,28\n"
        "BATCH-2026-B1,ROOM-102,2026-10-19,09:30,13:30,25\n"
    )

    files = {"file": ("schedule_valid.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/ingest/schedule", files=files)
    assert response.status_code == status.HTTP_201_CREATED

    res_json = response.json()
    assert res_json["inserted_records"] == 3
    assert res_json["updated_records"] == 0
    assert res_json["upload"]["status"] == "VALIDATED"
    assert res_json["upload"]["row_count"] == 3

    # Verify rows in database
    records = db_session.query(ScheduleRecord).filter(ScheduleRecord.batch_id == "BATCH-2026-A1").all()
    assert len(records) == 2


def test_schedule_deterministic_upsert(client, db_session):
    """
    Test that uploading revised schedules updates existing slots deterministically (idempotent upsert).
    """
    # 1. Initial import
    csv_1 = (
        "batch_id,classroom_id,class_date,start_time,end_time,enrolled_count\n"
        "BATCH-UPSERT,ROOM-101,2026-10-20,09:00,13:00,30\n"
        "BATCH-UPSERT,ROOM-101,2026-10-20,14:00,18:00,28\n"
    )
    res1 = client.post(
        "/api/ingest/schedule",
        files={"file": ("schedule_v1.csv", io.BytesIO(csv_1.encode("utf-8")), "text/csv")}
    )
    assert res1.status_code == status.HTTP_201_CREATED
    assert res1.json()["inserted_records"] == 2
    assert res1.json()["updated_records"] == 0

    # 2. Subsequent import with revision: slot 1 updated, slot 2 unchanged, slot 3 new
    csv_2 = (
        "batch_id,classroom_id,class_date,start_time,end_time,enrolled_count\n"
        "BATCH-UPSERT,ROOM-101,2026-10-20,09:00,13:30,35\n"  # Revision: end_time 13:30, enrolled 35
        "BATCH-UPSERT,ROOM-101,2026-10-20,14:00,18:00,28\n"  # Unchanged
        "BATCH-UPSERT,ROOM-102,2026-10-20,10:00,12:00,15\n"  # New slot
    )
    res2 = client.post(
        "/api/ingest/schedule",
        files={"file": ("schedule_v2.csv", io.BytesIO(csv_2.encode("utf-8")), "text/csv")}
    )
    assert res2.status_code == status.HTTP_201_CREATED
    assert res2.json()["inserted_records"] == 1
    assert res2.json()["updated_records"] == 2

    # Verify updated record in database
    updated_rec = (
        db_session.query(ScheduleRecord)
        .filter(
            ScheduleRecord.batch_id == "BATCH-UPSERT",
            ScheduleRecord.classroom_id == "ROOM-101",
            ScheduleRecord.start_time == time(9, 0),
        )
        .first()
    )
    assert updated_rec is not None
    assert updated_rec.end_time == time(13, 30)
    assert updated_rec.enrolled_count == 35


def test_schedule_reject_conflicting_intra_file_duplicates(client, db_session):
    """
    Test that conflicting duplicate schedule entries in a single CSV
    reject the entire file with all-or-nothing rollback and persistance of rejection audit.
    """
    csv_content = (
        "batch_id,classroom_id,class_date,start_time,end_time,enrolled_count\n"
        "BATCH-CONF,ROOM-101,2026-10-21,09:00,12:00,25\n"
        "BATCH-CONF,ROOM-101,2026-10-21,09:00,13:00,30\n"  # Conflicting with previous row
    )
    files = {"file": ("schedule_conflict.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/ingest/schedule", files=files)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    res_json = response.json()
    assert any("Conflicting duplicate schedule entry" in e for e in res_json["errors"])
    upload_id = res_json["upload_id"]

    # Verify 0 schedule records in database
    records = db_session.query(ScheduleRecord).filter(ScheduleRecord.batch_id == "BATCH-CONF").all()
    assert len(records) == 0

    # Verify REJECTED audit record exists in database
    audit = db_session.query(Upload).filter(Upload.id == upload_id).first()
    assert audit is not None
    assert audit.status == "REJECTED"


def test_schedule_reject_invalid_end_time_and_negative_enrollment(client, db_session):
    """
    Test that end_time <= start_time and negative enrolled_count are rejected.
    """
    csv_content = (
        "batch_id,classroom_id,class_date,start_time,end_time,enrolled_count\n"
        "BATCH-INV,ROOM-101,2026-10-22,14:00,10:00,20\n"   # Invalid end_time
        "BATCH-INV,ROOM-102,2026-10-22,09:00,11:00,-5\n"    # Negative enrolled_count
    )
    files = {"file": ("schedule_invalid.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/ingest/schedule", files=files)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    errors = response.json()["errors"]
    assert any("end_time (10:00) must be strictly after start_time (14:00)" in e for e in errors)
    assert any("enrolled_count must be a non-negative integer" in e for e in errors)
