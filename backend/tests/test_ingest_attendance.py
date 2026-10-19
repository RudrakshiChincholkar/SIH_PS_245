import io
from datetime import datetime, timezone
import pytest
from fastapi import status
from app.models import Upload, AttendanceRecord


def test_valid_attendance_csv_import(client, db_session):
    """
    Test uploading a valid mock AEBAS attendance CSV file.
    Verifies 201 Created and database persistence.
    """
    csv_content = (
        "batch_id,person_ref,punch_in,punch_out\n"
        "BATCH-2026-A1,CAND-001,2026-10-19 09:00:00,2026-10-19 13:00:00\n"
        "BATCH-2026-A1,CAND-002,2026-10-19 09:05:00,2026-10-19 13:02:00\n"
        "BATCH-2026-A1,CAND-003,2026-10-19 09:15:00,\n"
    )

    files = {"file": ("attendance_valid.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/ingest/attendance", files=files)
    assert response.status_code == status.HTTP_201_CREATED

    res_json = response.json()
    assert res_json["imported_records"] == 3
    assert res_json["upload"]["status"] == "VALIDATED"
    assert res_json["upload"]["row_count"] == 3

    # Verify rows in database
    records = db_session.query(AttendanceRecord).filter(AttendanceRecord.batch_id == "BATCH-2026-A1").all()
    assert len(records) == 3

    cand3 = next(r for r in records if r.person_ref == "CAND-003")
    assert cand3.punch_out is None


def test_timezone_naive_ist_to_utc_storage(client, db_session):
    """
    Explicit requirement: Naive timestamps are interpreted as IST and stored as UTC.
    Example: '2026-10-19 09:30:00' IST must represent '2026-10-19 04:00:00' UTC.
    """
    csv_content = (
        "batch_id,person_ref,punch_in,punch_out\n"
        "BATCH-TZ-TEST,CAND-TZ-1,2026-10-19 09:30:00,2026-10-19 17:30:00\n"
    )
    files = {"file": ("attendance_tz.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/ingest/attendance", files=files)
    assert response.status_code == status.HTTP_201_CREATED

    rec = db_session.query(AttendanceRecord).filter(AttendanceRecord.person_ref == "CAND-TZ-1").first()
    assert rec is not None

    # Expected UTC conversion:
    # 09:30:00 IST (UTC+05:30) - 5h 30m = 04:00:00 UTC
    # 17:30:00 IST (UTC+05:30) - 5h 30m = 12:00:00 UTC
    expected_punch_in = datetime(2026, 10, 19, 4, 0, 0, tzinfo=timezone.utc)
    expected_punch_out = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

    assert rec.punch_in == expected_punch_in
    assert rec.punch_out == expected_punch_out


def test_all_or_nothing_rollback_and_rejection_audit(client, db_session):
    """
    Explicit requirement: When a CSV contains an invalid row, ZERO records are inserted.
    The REJECTED upload record and validation errors MUST be persisted in the database.
    """
    csv_content = (
        "batch_id,person_ref,punch_in,punch_out\n"
        "BATCH-ROLLBACK,CAND-01,2026-10-19 09:00:00,2026-10-19 13:00:00\n"
        "BATCH-ROLLBACK,CAND-02,2026-10-19 09:05:00,2026-10-19 13:00:00\n"
        "BATCH-ROLLBACK,CAND-03,2026-10-19 12:00:00,2026-10-19 08:00:00\n"  # Invalid: punch_out earlier than punch_in
        "BATCH-ROLLBACK,CAND-04,2026-10-19 09:10:00,2026-10-19 13:00:00\n"
    )

    files = {"file": ("attendance_invalid.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/ingest/attendance", files=files)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    res_json = response.json()
    assert "punch_out (2026-10-19 08:00:00) cannot be earlier than punch_in" in str(res_json["errors"])
    upload_id = res_json["upload_id"]

    # 1. Verify zero attendance records exist in database
    records = db_session.query(AttendanceRecord).filter(AttendanceRecord.batch_id == "BATCH-ROLLBACK").all()
    assert len(records) == 0, "All-or-nothing failed: rows were inserted despite invalid row"

    # 2. Verify REJECTED upload audit record exists in database
    upload_audit = db_session.query(Upload).filter(Upload.id == upload_id).first()
    assert upload_audit is not None
    assert upload_audit.status == "REJECTED"
    assert upload_audit.row_count == 0
    assert "earlier than punch_in" in upload_audit.error_message


def test_reject_missing_required_headers(client, db_session):
    """
    Test rejection when required columns are missing in attendance CSV.
    """
    csv_content = (
        "batch_id,person_ref,punch_in\n"
        "BATCH-A1,CAND-1,2026-10-19 09:00:00\n"
    )
    files = {"file": ("bad_headers.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/ingest/attendance", files=files)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Invalid CSV headers" in response.json()["errors"][0]


def test_reject_intra_file_duplicate_punches(client, db_session):
    """
    Test detection and rejection of intra-file duplicate punch records.
    """
    csv_content = (
        "batch_id,person_ref,punch_in,punch_out\n"
        "BATCH-DUP,CAND-DUP,2026-10-19 09:00:00,2026-10-19 13:00:00\n"
        "BATCH-DUP,CAND-DUP,2026-10-19 09:00:00,2026-10-19 13:00:00\n"
    )
    files = {"file": ("duplicate_punch.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/ingest/attendance", files=files)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert any("Duplicate punch detected" in err for err in response.json()["errors"])


def test_reject_empty_attendance_file(client):
    """
    Test rejection of empty CSV file.
    """
    files = {"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    response = client.post("/api/ingest/attendance", files=files)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "CSV file is empty" in response.json()["errors"][0]
