import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Upload, VideoQualityAssessment, VideoQualitySample
from app.video_processor import (
    FROZEN_MIN_IDENTICAL_PAIRS,
    FLAG_COMPLETELY_BLACK,
    FLAG_DECODE_FAILURE,
    FLAG_LOW_LIGHT,
    FLAG_LOW_DECODE_RELIABILITY,
    FLAG_POSSIBLE_FROZEN_FOOTAGE,
    FLAG_POTENTIAL_BLUR,
    FLAG_UNREADABLE,
    QUALITY_DEGRADED,
    QUALITY_UNUSABLE,
    QUALITY_USABLE,
    classify_from_metrics,
    process_video,
    resolve_stored_video_path,
)
from tests.test_ingest_video import make_dummy_mp4


def _checkerboard_frame(h, w, phase, *, luminance_scale=1.0, offset=0, motion=True):
    """High-texture frame. Not a flat gradient (which must not 'prove' blur)."""
    yy, xx = np.mgrid[0:h, 0:w]
    cell = 16
    board = ((xx + phase) // cell + (yy + phase) // cell) % 2
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    light = int(np.clip(210 * luminance_scale + offset, 0, 255))
    dark = int(np.clip(50 * luminance_scale + offset, 0, 255))
    frame[board == 1] = (light, int(light * 0.9), int(light * 0.7))
    frame[board == 0] = (dark, int(min(255, dark + 40)), int(min(255, dark + 90)))
    if motion:
        # Moving block adds temporal variation independent of the checkerboard phase.
        x0 = (phase * 3) % max(1, w - 40)
        cv2.rectangle(frame, (x0, 20), (x0 + 36, 70), (20, 200, 255), -1)
    return frame


def write_synthetic_video(path: Path, frames, fps=10):
    """Write frames with mp4v. Fails the test if the local codec cannot encode."""
    path = Path(path)
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        writer.release()
        pytest.skip("OpenCV VideoWriter mp4v is unavailable in this environment")
    for frame in frames:
        writer.write(frame)
    writer.release()
    assert path.exists() and path.stat().st_size > 0


def ingest_placeholder_video(client, batch_id, classroom_id, slot):
    mp4_bytes = make_dummy_mp4(2048)
    response = client.post(
        "/api/ingest/video",
        files={"file": (f"{batch_id}.mp4", io.BytesIO(mp4_bytes), "video/mp4")},
        data={
            "batch_id": batch_id,
            "classroom_id": classroom_id,
            "recording_date_time": slot,
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()["upload"]["id"]


def replace_with_synthetic(db_session, upload_id, frames, fps=10):
    upload = db_session.query(Upload).filter(Upload.id == upload_id).first()
    dest = settings.video_upload_dir / upload.stored_filename
    write_synthetic_video(dest, frames, fps=fps)
    return dest


def textured_frames(n, fps=10, h=180, w=320):
    return [_checkerboard_frame(h, w, phase=i * 4) for i in range(n)]


def test_resolve_path_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        resolve_stored_video_path("../secret.mp4", tmp_path)
    with pytest.raises(ValueError):
        resolve_stored_video_path("subdir/file.mp4", tmp_path)
    safe = tmp_path / "abc.mp4"
    safe.write_bytes(b"x")
    resolved = resolve_stored_video_path("abc.mp4", tmp_path)
    assert resolved == safe.resolve()


def test_classify_does_not_flag_frozen_from_one_pair():
    quality, flags, _ = classify_from_metrics(
        capture_opened=True,
        samples_attempted=2,
        samples_successful=2,
        avg_blur_score=250.0,
        avg_luminance=120.0,
        identical_pairs=1,
        temporal_pairs=1,
        decode_success_ratio=1.0,
    )
    assert FLAG_POSSIBLE_FROZEN_FOOTAGE not in flags
    assert quality == QUALITY_USABLE
    assert FROZEN_MIN_IDENTICAL_PAIRS >= 3


def test_valid_textured_video_is_usable(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-TEX", "ROOM-Q1", "2026-10-19 09:00:00")
    replace_with_synthetic(db_session, upload_id, textured_frames(50), fps=10)

    res = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")
    assert res.status_code == status.HTTP_200_OK
    body = res.json()
    assert "/home/" not in res.text
    assessment = body["assessment"]
    assert assessment["processing_status"] == "COMPLETED"
    assert assessment["overall_quality"] == QUALITY_USABLE
    assert assessment["samples_successful"] >= 4
    assert assessment["decode_success_ratio"] >= 0.8
    assert assessment["avg_blur_score"] is not None and assessment["avg_blur_score"] > 100
    assert assessment["avg_temporal_difference"] is not None
    assert FLAG_POTENTIAL_BLUR not in assessment["quality_flags"]
    assert "does not count people" in assessment["safety_note"].lower()

    stored = db_session.query(VideoQualityAssessment).filter_by(upload_id=upload_id).one()
    assert stored.overall_quality == QUALITY_USABLE
    samples = (
        db_session.query(VideoQualitySample)
        .filter_by(upload_id=upload_id)
        .order_by(VideoQualitySample.sample_index)
        .all()
    )
    assert len(samples) == assessment["samples_attempted"]
    assert samples[0].timestamp_seconds == 0.0
    assert samples[0].status == "USABLE"


def test_dark_footage_flags_low_light(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-DARK", "ROOM-Q1", "2026-10-19 09:05:00")
    frames = [np.full((180, 320, 3), 25, dtype=np.uint8) for _ in range(40)]
    replace_with_synthetic(db_session, upload_id, frames, fps=10)

    res = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")
    assert res.status_code == status.HTTP_200_OK
    assessment = res.json()["assessment"]
    assert assessment["avg_luminance"] is not None
    assert assessment["avg_luminance"] < 40
    assert FLAG_LOW_LIGHT in assessment["quality_flags"] or assessment["overall_quality"] == QUALITY_UNUSABLE
    assert assessment["overall_quality"] in {QUALITY_DEGRADED, QUALITY_UNUSABLE}
    assert "zero occupancy" in (assessment["diagnostic_message"] or "").lower() or "zero occupancy" in assessment["safety_note"].lower()


def test_overexposed_footage_flags_high_luminance(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-OVER", "ROOM-Q1", "2026-10-19 09:05:30")
    frames = [np.full((180, 320, 3), 250, dtype=np.uint8) for _ in range(30)]
    replace_with_synthetic(db_session, upload_id, frames, fps=10)

    response = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")

    assert response.status_code == status.HTTP_200_OK
    assessment = response.json()["assessment"]
    assert assessment["avg_luminance"] > 230
    assert "OVEREXPOSURE" in assessment["quality_flags"]
    assert assessment["overall_quality"] == QUALITY_DEGRADED
    assert assessment["samples_successful"] >= 2
    assert assessment["avg_temporal_difference"] is not None


def test_black_footage_is_unusable(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-BLK", "ROOM-Q1", "2026-10-19 09:06:00")
    frames = [np.zeros((180, 320, 3), dtype=np.uint8) for _ in range(30)]
    replace_with_synthetic(db_session, upload_id, frames, fps=10)

    res = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")
    assert res.status_code == status.HTTP_200_OK
    assessment = res.json()["assessment"]
    assert assessment["overall_quality"] == QUALITY_UNUSABLE
    assert FLAG_COMPLETELY_BLACK in assessment["quality_flags"]


def test_gaussian_blurred_footage_flags_potential_blur(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-BLUR", "ROOM-Q1", "2026-10-19 09:07:00")
    sharp = textured_frames(40)
    blurred = [cv2.GaussianBlur(frame, (31, 31), 8) for frame in sharp]
    replace_with_synthetic(db_session, upload_id, blurred, fps=10)

    res = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")
    assert res.status_code == status.HTTP_200_OK
    assessment = res.json()["assessment"]
    assert FLAG_POTENTIAL_BLUR in assessment["quality_flags"]
    assert assessment["overall_quality"] == QUALITY_DEGRADED
    assert assessment["avg_blur_score"] < 100


def test_repeated_identical_frames_flag_possible_frozen(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-FRZ", "ROOM-Q1", "2026-10-19 09:08:00")
    still = _checkerboard_frame(180, 320, phase=0)
    frames = [still.copy() for _ in range(50)]
    replace_with_synthetic(db_session, upload_id, frames, fps=10)

    res = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")
    assert res.status_code == status.HTTP_200_OK
    assessment = res.json()["assessment"]
    assert assessment["samples_successful"] >= 4
    assert FLAG_POSSIBLE_FROZEN_FOOTAGE in assessment["quality_flags"]
    assert assessment["overall_quality"] == QUALITY_DEGRADED


def test_sampling_counts_change_with_interval(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-SMP", "ROOM-Q1", "2026-10-19 09:09:00")
    replace_with_synthetic(db_session, upload_id, textured_frames(50), fps=10)

    fine = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")
    coarse = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=2")
    assert fine.status_code == status.HTTP_200_OK
    assert coarse.status_code == status.HTTP_200_OK
    fine_n = fine.json()["assessment"]["samples_attempted"]
    coarse_n = coarse.json()["assessment"]["samples_attempted"]
    assert fine_n >= 4
    assert coarse_n >= 2
    assert coarse_n < fine_n
    assert coarse.json()["assessment"]["sample_interval_seconds"] == 2.0

    rows = db_session.query(VideoQualityAssessment).filter_by(upload_id=upload_id).all()
    assert len(rows) == 1
    assert rows[0].analysis_count == 2


def test_corrupt_video_unusable(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-BAD", "ROOM-Q1", "2026-10-19 09:10:00")
    upload = db_session.query(Upload).filter(Upload.id == upload_id).first()
    dest = settings.video_upload_dir / upload.stored_filename
    dest.write_bytes(make_dummy_mp4(4096))

    res = client.post(f"/api/videos/{upload_id}/process")
    assert res.status_code == status.HTTP_200_OK
    assessment = res.json()["assessment"]
    assert assessment["overall_quality"] == QUALITY_UNUSABLE
    assert FLAG_UNREADABLE in assessment["quality_flags"]
    assert FLAG_DECODE_FAILURE in assessment["quality_flags"]
    assert FLAG_LOW_DECODE_RELIABILITY in assessment["quality_flags"]
    assert assessment["samples_attempted"] == assessment["samples_failed"] == 1
    assert assessment["samples_successful"] == 0
    assert assessment["processing_status"] == "COMPLETED"


def test_missing_file_is_not_successfully_assessed(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-MISS", "ROOM-Q1", "2026-10-19 09:11:00")
    upload = db_session.query(Upload).filter(Upload.id == upload_id).first()
    dest = settings.video_upload_dir / upload.stored_filename
    dest.unlink()

    res = client.post(f"/api/videos/{upload_id}/process")
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    row = db_session.query(VideoQualityAssessment).filter_by(upload_id=upload_id).one()
    assert row.processing_status == "FAILED"
    assert row.overall_quality is None


def test_invalid_and_missing_upload_ids(client, db_session):
    missing = "00000000-0000-0000-0000-000000000000"
    process_res = client.post(f"/api/videos/{missing}/process")
    assert process_res.status_code == status.HTTP_404_NOT_FOUND
    get_res = client.get(f"/api/videos/{missing}/quality")
    assert get_res.status_code == status.HTTP_404_NOT_FOUND

    csv_payload = "batch_id,person_ref,punch_in,punch_out\nBATCH-Q-CSV,CAND-1,2026-10-19 09:00:00,\n"
    att = client.post(
        "/api/ingest/attendance",
        files={"file": ("att.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")},
    )
    att_id = att.json()["upload"]["id"]
    not_video = client.post(f"/api/videos/{att_id}/process")
    assert not_video.status_code == status.HTTP_400_BAD_REQUEST

    video_id = ingest_placeholder_video(client, "BATCH-Q-NA", "ROOM-Q1", "2026-10-19 09:12:00")
    no_assessment = client.get(f"/api/videos/{video_id}/quality")
    assert no_assessment.status_code == status.HTTP_404_NOT_FOUND


def test_invalid_sample_intervals(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-INT", "ROOM-Q1", "2026-10-19 09:13:00")
    for value in (0, -5, 0.1, 120, "NaN", "inf"):
        res = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds={value}")
        assert res.status_code == status.HTTP_400_BAD_REQUEST


def test_repeat_processing_updates_single_row(client, db_session):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-REP", "ROOM-Q1", "2026-10-19 09:14:00")
    replace_with_synthetic(db_session, upload_id, textured_frames(40), fps=10)

    first = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")
    second = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")
    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_200_OK
    rows = db_session.query(VideoQualityAssessment).filter_by(upload_id=upload_id).all()
    assert len(rows) == 1
    assert rows[0].analysis_count == 2
    assert rows[0].processing_status == "COMPLETED"

    fetched = client.get(f"/api/videos/{upload_id}/quality")
    assert fetched.status_code == status.HTTP_200_OK
    assert fetched.json()["upload_id"] == upload_id
    assert fetched.json()["analysis_count"] == 2
    assert fetched.json()["avg_temporal_difference"] is not None


def test_persistence_rollback_on_commit_failure(client, db_session, monkeypatch):
    upload_id = ingest_placeholder_video(client, "BATCH-Q-RB", "ROOM-Q1", "2026-10-19 09:15:00")
    replace_with_synthetic(db_session, upload_id, textured_frames(20), fps=10)

    def boom(self):
        raise RuntimeError("forced persistence failure")

    monkeypatch.setattr(Session, "commit", boom)
    res = client.post(f"/api/videos/{upload_id}/process?sample_interval_seconds=1")
    assert res.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    monkeypatch.undo()

    leftover = db_session.query(VideoQualityAssessment).filter_by(upload_id=upload_id).all()
    assert leftover == []


def test_capture_released_on_success_and_corrupt(monkeypatch, tmp_path):
    releases = []
    real_capture = cv2.VideoCapture

    class TrackingCapture:
        def __init__(self, *args, **kwargs):
            self._inner = real_capture(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def release(self):
            releases.append(True)
            return self._inner.release()

    monkeypatch.setattr(cv2, "VideoCapture", TrackingCapture)

    good = tmp_path / "good.mp4"
    write_synthetic_video(good, textured_frames(15), fps=10)
    process_video(good, sample_interval_seconds=0.5)

    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(make_dummy_mp4(1024))
    process_video(corrupt, sample_interval_seconds=1.0)

    missing = tmp_path / "nope.mp4"
    process_video(missing, sample_interval_seconds=1.0)

    assert len(releases) >= 2


def test_early_decode_stop_counts_failed_sample_and_flags(monkeypatch, tmp_path):
    path = tmp_path / "truncated.mp4"
    path.write_bytes(b"synthetic")

    class EarlyStopCapture:
        def __init__(self, *_args, **_kwargs):
            self.reads = 0

        def isOpened(self):
            return True

        def get(self, prop):
            return {
                cv2.CAP_PROP_FRAME_WIDTH: 320,
                cv2.CAP_PROP_FRAME_HEIGHT: 180,
                cv2.CAP_PROP_FPS: 1,
                cv2.CAP_PROP_FRAME_COUNT: 4,
            }.get(prop, 0)

        def read(self):
            self.reads += 1
            if self.reads == 1:
                return True, _checkerboard_frame(180, 320, phase=0)
            return False, None

        def release(self):
            self.released = True

    capture = EarlyStopCapture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_args, **_kwargs: capture)

    result = process_video(path, sample_interval_seconds=1)

    assert result.samples_attempted == 2
    assert result.samples_successful == 1
    assert result.samples_failed == 1
    assert result.decode_success_ratio == 0.5
    assert FLAG_DECODE_FAILURE in result.quality_flags
    assert FLAG_LOW_DECODE_RELIABILITY in result.quality_flags
    assert capture.released


def test_process_video_missing_file_unit(tmp_path):
    result = process_video(tmp_path / "absent.mp4", sample_interval_seconds=10)
    assert result.input_missing is True
    assert result.overall_quality == QUALITY_UNUSABLE
    assert result.capture_opened is False
