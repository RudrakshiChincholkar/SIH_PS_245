import io
import pytest
from fastapi import status
from tests.test_ingest_video import make_dummy_mp4



def test_list_and_filter_uploads(client):
    """
    Test listing uploads with status/type filtering and pagination.
    """
    # 1. Ingest a video
    mp4_bytes = make_dummy_mp4(1024)
    client.post(
        "/api/ingest/video",
        files={"file": ("list_test.mp4", io.BytesIO(mp4_bytes), "video/mp4")},
        data={"batch_id": "BATCH-LIST", "classroom_id": "ROOM-L1", "recording_date_time": "2026-10-19 09:00:00"},
    )

    # 2. Ingest an attendance CSV
    att_csv = "batch_id,person_ref,punch_in,punch_out\nBATCH-LIST,CAND-L1,2026-10-19 09:00:00,\n"
    client.post(
        "/api/ingest/attendance",
        files={"file": ("list_att.csv", io.BytesIO(att_csv.encode("utf-8")), "text/csv")},
    )

    # 3. List all
    res_all = client.get("/api/ingest/uploads")
    assert res_all.status_code == status.HTTP_200_OK
    data = res_all.json()
    assert data["total"] >= 2
    assert len(data["items"]) >= 2

    # 4. Filter by upload_type=video
    res_vid = client.get("/api/ingest/uploads?upload_type=video")
    assert res_vid.status_code == status.HTTP_200_OK
    assert all(item["upload_type"] == "video" for item in res_vid.json()["items"])

    # 5. Filter by status=VALIDATED
    res_val = client.get("/api/ingest/uploads?status=VALIDATED")
    assert res_val.status_code == status.HTTP_200_OK
    assert all(item["status"] == "VALIDATED" for item in res_val.json()["items"])


def test_get_upload_detail_and_404(client):
    """
    Test retrieving detail for a single upload and 404 for unknown ID.
    """
    att_csv = "batch_id,person_ref,punch_in,punch_out\nBATCH-DET,CAND-D1,2026-10-19 09:00:00,\n"
    post_res = client.post(
        "/api/ingest/attendance",
        files={"file": ("detail_att.csv", io.BytesIO(att_csv.encode("utf-8")), "text/csv")},
    )
    upload_id = post_res.json()["upload"]["id"]

    # Valid detail lookup
    res = client.get(f"/api/ingest/uploads/{upload_id}")
    assert res.status_code == status.HTTP_200_OK
    detail = res.json()
    assert detail["id"] == upload_id
    assert detail["original_filename"] == "detail_att.csv"

    # Non-existent ID lookup
    res_404 = client.get("/api/ingest/uploads/00000000-0000-0000-0000-000000000000")
    assert res_404.status_code == status.HTTP_404_NOT_FOUND


def test_download_csv_templates(client):
    """
    Test endpoints serving sample CSV templates.
    """
    res_att = client.get("/api/ingest/templates/attendance")
    assert res_att.status_code == status.HTTP_200_OK
    assert "batch_id,person_ref,punch_in,punch_out" in res_att.text

    res_sch = client.get("/api/ingest/templates/schedule")
    assert res_sch.status_code == status.HTTP_200_OK
    assert "batch_id,classroom_id,class_date,start_time,end_time,enrolled_count" in res_sch.text
