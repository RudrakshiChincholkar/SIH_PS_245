import io
import pytest
from fastapi import status
from app.config import settings
from app.models import Upload, VideoMetadata


def make_dummy_mp4(size_bytes: int = 1024) -> bytes:
    """Creates dummy byte sequence with valid MP4 ftyp container header."""
    header = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41"
    padding = b"\x00" * max(0, size_bytes - len(header))
    return header + padding


def make_dummy_avi(size_bytes: int = 1024) -> bytes:
    """Creates dummy byte sequence with valid AVI container header."""
    header = b"RIFF\x24\x00\x00\x00AVI LIST\x00\x00\x00\x00"
    padding = b"\x00" * max(0, size_bytes - len(header))
    return header + padding


def make_dummy_mov(size_bytes: int = 1024) -> bytes:
    """Creates dummy byte sequence with valid MOV container header."""
    header = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  "
    padding = b"\x00" * max(0, size_bytes - len(header))
    return header + padding


def test_upload_valid_mp4_video(client, db_session):
    """
    Test uploading a valid MP4 video with metadata.
    Verifies 201 Created, safe UUID filename, and no absolute path leakage.
    """
    mp4_bytes = make_dummy_mp4(2048)
    files = {"file": ("cctv_hall1.mp4", io.BytesIO(mp4_bytes), "video/mp4")}
    data = {
        "batch_id": "BATCH-2026-A1",
        "classroom_id": "ROOM-101",
        "recording_date_time": "2026-10-19 09:30:00",
    }

    response = client.post("/api/ingest/video", files=files, data=data)
    assert response.status_code == status.HTTP_201_CREATED

    res_json = response.json()
    assert res_json["upload"]["status"] == "VALIDATED"
    assert res_json["upload"]["original_filename"] == "cctv_hall1.mp4"
    assert res_json["upload"]["file_size_bytes"] == len(mp4_bytes)
    assert res_json["video_metadata"]["batch_id"] == "BATCH-2026-A1"
    assert res_json["video_metadata"]["classroom_id"] == "ROOM-101"
    assert res_json["video_metadata"]["file_format"] == "mp4"

    # Security check: verify absolute filesystem paths are NOT leaked in response
    res_str = response.text
    assert "/home/" not in res_str
    assert "/tmp/" not in res_str

    # Verify database persistence
    upload_id = res_json["upload"]["id"]
    upload_row = db_session.query(Upload).filter(Upload.id == upload_id).first()
    assert upload_row is not None
    assert upload_row.stored_filename.endswith(".mp4")

    # Verify file saved on disk
    saved_file = settings.video_upload_dir / upload_row.stored_filename
    assert saved_file.exists()
    assert saved_file.stat().st_size == len(mp4_bytes)


def test_upload_valid_avi_and_mov_video(client, db_session):
    """
    Test uploading valid AVI and MOV container formats.
    """
    # 1. Test AVI
    avi_bytes = make_dummy_avi(1024)
    files_avi = {"file": ("recording1.avi", io.BytesIO(avi_bytes), "video/x-msvideo")}
    data_avi = {
        "batch_id": "BATCH-2026-AVI",
        "classroom_id": "ROOM-AVI",
        "recording_date_time": "2026-10-19 10:00:00",
    }
    res_avi = client.post("/api/ingest/video", files=files_avi, data=data_avi)
    assert res_avi.status_code == status.HTTP_201_CREATED
    assert res_avi.json()["video_metadata"]["file_format"] == "avi"

    # 2. Test MOV
    mov_bytes = make_dummy_mov(1024)
    files_mov = {"file": ("recording2.mov", io.BytesIO(mov_bytes), "video/quicktime")}
    data_mov = {
        "batch_id": "BATCH-2026-MOV",
        "classroom_id": "ROOM-MOV",
        "recording_date_time": "2026-10-19 11:00:00",
    }
    res_mov = client.post("/api/ingest/video", files=files_mov, data=data_mov)
    assert res_mov.status_code == status.HTTP_201_CREATED
    assert res_mov.json()["video_metadata"]["file_format"] == "mov"


def test_reject_unsupported_extension(client):
    """
    Test rejection of unsupported file extensions (e.g. .exe, .txt).
    """
    files = {"file": ("script.exe", io.BytesIO(b"MZ\x90\x00binary"), "application/octet-stream")}
    data = {
        "batch_id": "BATCH-EXE",
        "classroom_id": "ROOM-101",
        "recording_date_time": "2026-10-19 09:30:00",
    }
    response = client.post("/api/ingest/video", files=files, data=data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Unsupported file extension" in response.json()["detail"]


def test_reject_invalid_magic_bytes_and_cleanup(client):
    """
    Test that a file with .mp4 extension but invalid container magic bytes
    is rejected with 415 and cleanly unlinked from disk.
    """
    corrupted_bytes = b"Hello, this is just plain text masquerading as an MP4 video file!"
    files = {"file": ("fake_video.mp4", io.BytesIO(corrupted_bytes), "video/mp4")}
    data = {
        "batch_id": "BATCH-FAKE",
        "classroom_id": "ROOM-101",
        "recording_date_time": "2026-10-19 09:30:00",
    }

    initial_files = set(settings.video_upload_dir.glob("*"))

    response = client.post("/api/ingest/video", files=files, data=data)
    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert "Invalid media format" in response.json()["detail"]

    # Verify no leaked or residual files in the storage directory
    current_files = set(settings.video_upload_dir.glob("*"))
    assert current_files == initial_files


def test_reject_oversized_video_stream(client, monkeypatch):
    """
    Test that video streaming cutoff triggers when bytes exceed MAX_VIDEO_SIZE_MB,
    returning HTTP 413 and deleting the partial file.
    """
    # Temporarily set max size to 1 MB for the test
    monkeypatch.setattr(settings, "MAX_VIDEO_SIZE_MB", 1)

    # Create 1.5 MB dummy video
    oversized_bytes = make_dummy_mp4(size_bytes=int(1.5 * 1024 * 1024))
    files = {"file": ("oversized.mp4", io.BytesIO(oversized_bytes), "video/mp4")}
    data = {
        "batch_id": "BATCH-OVERSIZED",
        "classroom_id": "ROOM-101",
        "recording_date_time": "2026-10-19 09:30:00",
    }

    initial_files = set(settings.video_upload_dir.glob("*"))

    response = client.post("/api/ingest/video", files=files, data=data)
    assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert "exceeds maximum permitted upload limit" in response.json()["detail"]

    # Verify file was cleaned up on disk
    current_files = set(settings.video_upload_dir.glob("*"))
    assert current_files == initial_files


def test_reject_duplicate_video_slot_and_cleanup(client):
    """
    Test duplicate video submission for same (batch_id, classroom_id, recording_date_time).
    Second submission must return HTTP 409 and not leave duplicate files on disk.
    """
    mp4_bytes = make_dummy_mp4(1024)
    data = {
        "batch_id": "BATCH-DUP",
        "classroom_id": "ROOM-202",
        "recording_date_time": "2026-10-19 14:00:00",
    }

    # 1. First upload succeeds
    res1 = client.post(
        "/api/ingest/video",
        files={"file": ("video1.mp4", io.BytesIO(mp4_bytes), "video/mp4")},
        data=data,
    )
    assert res1.status_code == status.HTTP_201_CREATED

    files_after_first = set(settings.video_upload_dir.glob("*"))
    assert len(files_after_first) == 1

    # 2. Second upload for identical slot returns 409 Conflict
    res2 = client.post(
        "/api/ingest/video",
        files={"file": ("video2.mp4", io.BytesIO(mp4_bytes), "video/mp4")},
        data=data,
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already registered" in res2.json()["detail"]

    # Verify second file was cleaned up and did not remain on disk
    files_after_second = set(settings.video_upload_dir.glob("*"))
    assert files_after_second == files_after_first
