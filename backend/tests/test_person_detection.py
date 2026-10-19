import io
import sys
import types
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi import status
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import (
    OccupancyFrame,
    Upload,
    Upload as UploadModel,
    VideoQualityAssessment,
    VideoQualitySample,
)
from app.occupancy_processor import (
    FRAME_UNUSABLE,
    FRAME_USABLE,
    process_occupancy_video,
)
from app.person_detector import (
    DetectorUnavailableError,
    PersonDetection,
    YOLOPersonDetector,
    filter_and_suppress_detections,
)
from app.video_processor import QUALITY_USABLE
from app.video_processor import FrameQualityResult
from tests.test_ingest_video import make_dummy_mp4
from scripts.migrate_occupancy_frames import migrate_occupancy_frames


def usable_frame():
    yy, xx = np.mgrid[0:180, 0:320]
    board = ((xx // 12) + (yy // 12)) % 2
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    frame[board == 1] = (230, 230, 230)
    frame[board == 0] = (40, 40, 40)
    cv2.rectangle(frame, (80, 40), (130, 150), (30, 160, 230), -1)
    return frame


class FakeCapture:
    def __init__(self, frames, fps=1.0):
        self.frames = list(frames)
        self.fps = fps
        self.position = 0
        self.released = False

    def isOpened(self):
        return True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return self.fps
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return len(self.frames)
        return 0

    def read(self):
        if self.position >= len(self.frames):
            return False, None
        frame = self.frames[self.position]
        self.position += 1
        return True, frame.copy()

    def release(self):
        self.released = True


class FakeDetector:
    confidence_threshold = 0.25
    iou_threshold = 0.45

    def __init__(self, detections=None, error=None):
        self.detections = detections or []
        self.error = error
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return list(self.detections)


def test_detector_filters_person_confidence_and_overlapping_boxes(monkeypatch):
    class Tensor:
        def __init__(self, values):
            self.values = np.asarray(values)

        def cpu(self):
            return self

        def numpy(self):
            return self.values

    class Boxes:
        xyxy = Tensor([[10, 10, 100, 100], [12, 12, 98, 98], [150, 10, 200, 100]])
        conf = Tensor([0.91, 0.82, 0.99])
        cls = Tensor([0, 0, 1])

    class Result:
        boxes = Boxes()

    class FakeModel:
        def __init__(self):
            self.call = None

        def predict(self, **kwargs):
            self.call = kwargs
            return [Result()]

    model = FakeModel()
    module = types.ModuleType("ultralytics")
    module.YOLO = lambda _path: model
    monkeypatch.setitem(sys.modules, "ultralytics", module)

    detector = YOLOPersonDetector()
    detections = detector.detect(usable_frame())

    assert model.call["device"] == "cpu"
    assert model.call["classes"] == [0]
    assert model.call["conf"] == settings.PERSON_DETECTION_CONFIDENCE
    assert len(detections) == 1
    assert detections[0].confidence == pytest.approx(0.91)

    filtered = filter_and_suppress_detections(
        [PersonDetection([1, 1, 20, 20], 0.24), PersonDetection([30, 30, 50, 50], 0.8)],
        confidence_threshold=0.25,
        iou_threshold=0.45,
    )
    assert len(filtered) == 1
    assert filtered[0].confidence == pytest.approx(0.8)


def test_unusable_frame_is_not_counted_and_capture_is_released(monkeypatch, tmp_path):
    capture = FakeCapture([np.zeros((180, 320, 3), dtype=np.uint8), usable_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: capture)
    detector = FakeDetector([PersonDetection([80, 40, 130, 150], 0.88)])

    result = process_occupancy_video(
        tmp_path / "registered.mp4",
        "upload-id",
        1.0,
        detector,
    )

    assert [sample["status"] for sample in result.frames] == [FRAME_UNUSABLE, FRAME_USABLE]
    assert result.frames[0]["person_count"] is None
    assert result.frames[1]["person_count"] == 1
    assert detector.calls == 1
    assert capture.released


def test_frame_results_stream_to_callback_without_retaining_list(monkeypatch, tmp_path):
    capture = FakeCapture([usable_frame() for _ in range(4)])
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: capture)
    monkeypatch.setattr(
        "app.occupancy_processor.assess_frame_quality",
        lambda _frame: FrameQualityResult(250.0, 120.0, []),
    )
    emitted = []
    result = process_occupancy_video(
        tmp_path / "registered.mp4",
        "upload-id",
        1.0,
        FakeDetector(),
        frame_callback=emitted.append,
    )

    assert result.frames == []
    assert len(emitted) == 4
    assert result.samples_processed == 4


def test_part3_unusable_assessment_skips_all_detection(monkeypatch, tmp_path):
    capture = FakeCapture([usable_frame(), usable_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: capture)
    detector = FakeDetector([PersonDetection([80, 40, 130, 150], 0.88)])

    result = process_occupancy_video(
        tmp_path / "registered.mp4",
        "upload-id",
        1.0,
        detector,
        globally_unusable=True,
        global_quality_flags=["COMPLETELY_BLACK"],
    )

    assert result.samples_unusable == 2
    assert detector.calls == 0
    assert all(sample["person_count"] is None for sample in result.frames)


def test_optional_evidence_saved_only_for_usable_frames(monkeypatch, tmp_path):
    capture = FakeCapture([usable_frame(), np.zeros((180, 320, 3), dtype=np.uint8)])
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: capture)
    monkeypatch.setattr(
        "app.occupancy_processor.assess_frame_quality",
        lambda frame: FrameQualityResult(
            250.0 if frame.mean() > 50 else 0.0,
            120.0 if frame.mean() > 50 else 0.0,
            [] if frame.mean() > 50 else ["LOW_LIGHT"],
        ),
    )
    detector = FakeDetector([PersonDetection([80, 40, 130, 150], 0.88)])

    result = process_occupancy_video(
        tmp_path / "registered.mp4",
        "upload-id",
        1.0,
        detector,
        evidence_enabled=True,
        evidence_dir=tmp_path / "evidence",
        max_evidence_frames=1,
        evidence_run_id="run-test",
    )

    assert result.frames[0]["status"] == FRAME_USABLE
    assert result.frames[0]["evidence_path"] == "upload-id/run-test/000000.jpg"
    assert (tmp_path / "evidence" / result.frames[0]["evidence_path"]).is_file()
    assert result.frames[1]["status"] == FRAME_UNUSABLE
    assert result.frames[1]["evidence_path"] is None
    assert result.frames[1]["person_count"] is None


def test_zero_detection_frame_gets_bounded_evidence_when_enabled(monkeypatch, tmp_path):
    capture = FakeCapture([usable_frame(), usable_frame(), usable_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: capture)
    monkeypatch.setattr(
        "app.occupancy_processor.assess_frame_quality",
        lambda _frame: FrameQualityResult(250.0, 120.0, []),
    )
    overlay_text = []
    original_put_text = cv2.putText

    def record_overlay(image, text, *args, **kwargs):
        overlay_text.append(text)
        return original_put_text(image, text, *args, **kwargs)

    monkeypatch.setattr(cv2, "putText", record_overlay)
    result = process_occupancy_video(
        tmp_path / "registered.mp4",
        "upload-id",
        1.0,
        FakeDetector(),
        evidence_enabled=True,
        evidence_dir=tmp_path / "evidence",
        max_evidence_frames=2,
        evidence_run_id="zero-run",
    )

    assert [frame["person_count"] for frame in result.frames] == [0, 0, 0]
    assert [frame["evidence_path"] is not None for frame in result.frames] == [True, True, False]
    assert all(frame["status"] == FRAME_USABLE for frame in result.frames)
    assert overlay_text.count("YOLO person count: 0") == 2


def test_evidence_disabled_creates_no_files(monkeypatch, tmp_path):
    capture = FakeCapture([usable_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: capture)
    monkeypatch.setattr(
        "app.occupancy_processor.assess_frame_quality",
        lambda _frame: FrameQualityResult(250.0, 120.0, []),
    )
    evidence_dir = tmp_path / "evidence"
    result = process_occupancy_video(
        tmp_path / "registered.mp4",
        "upload-id",
        1.0,
        FakeDetector(),
        evidence_enabled=False,
        evidence_dir=evidence_dir,
    )

    assert result.frames[0]["person_count"] == 0
    assert result.frames[0]["evidence_path"] is None
    assert not evidence_dir.exists()


def _registered_video(client, db_session, batch="BATCH-P4", room="ROOM-P4"):
    response = client.post(
        "/api/ingest/video",
        files={"file": ("sample.mp4", io.BytesIO(make_dummy_mp4(2048)), "video/mp4")},
        data={
            "batch_id": batch,
            "classroom_id": room,
            "recording_date_time": "2026-10-19 10:00:00",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    upload_id = response.json()["upload"]["id"]
    db_session.add(
        VideoQualityAssessment(
            upload_id=upload_id,
            processing_status="COMPLETED",
            overall_quality=QUALITY_USABLE,
            sample_interval_seconds=1.0,
            samples_attempted=2,
            samples_successful=2,
            samples_failed=0,
            quality_flags=[],
        )
    )
    db_session.commit()
    return upload_id


def test_occupancy_api_persists_idempotently_and_lists_frames(client, db_session, monkeypatch):
    upload_id = _registered_video(client, db_session)
    db_session.add_all(
        [
            VideoQualitySample(
                upload_id=upload_id,
                sample_index=0,
                timestamp_seconds=0.0,
                status="USABLE",
                blur_score=250.0,
                luminance=120.0,
                quality_flags=[],
            ),
            VideoQualitySample(
                upload_id=upload_id,
                sample_index=1,
                timestamp_seconds=1.0,
                status="USABLE",
                blur_score=250.0,
                luminance=120.0,
                quality_flags=[],
            ),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(settings, "OCCUPANCY_EVIDENCE_ENABLED", True)
    monkeypatch.setattr(settings, "OCCUPANCY_EVIDENCE_MAX_FRAMES", 2)
    overlay_text = []
    original_put_text = cv2.putText

    def record_overlay(image, text, *args, **kwargs):
        overlay_text.append(text)
        return original_put_text(image, text, *args, **kwargs)

    monkeypatch.setattr(cv2, "putText", record_overlay)
    captures = []

    def open_capture(_path):
        capture = FakeCapture([usable_frame(), usable_frame()])
        captures.append(capture)
        return capture

    monkeypatch.setattr(cv2, "VideoCapture", open_capture)
    monkeypatch.setattr(
        "app.occupancy_processor.assess_frame_quality",
        lambda _frame: FrameQualityResult(250.0, 120.0, []),
    )
    class PositiveThenZeroDetector(FakeDetector):
        def __init__(self):
            super().__init__()

        def detect(self, frame):
            self.calls += 1
            if self.calls == 1:
                return [PersonDetection([80, 40, 130, 150], 0.91)]
            return []

    monkeypatch.setattr(
        "app.routes.occupancy.YOLOPersonDetector",
        PositiveThenZeroDetector,
    )
    monkeypatch.setattr(
        "app.occupancy_processor.assess_frame_quality",
        lambda _frame: FrameQualityResult(250.0, 120.0, []),
    )

    first = client.post(f"/api/videos/{upload_id}/occupancy/process")
    second = client.post(f"/api/videos/{upload_id}/occupancy/process")

    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_200_OK
    assert second.json()["samples_processed"] == 2
    assert second.json()["samples_unusable"] == 0
    records = db_session.query(OccupancyFrame).filter_by(upload_id=upload_id).all()
    assert len(records) == 2
    assert [record.person_count for record in records] == [1, 0]
    assert [record.timestamp_seconds for record in records] == [0.0, 1.0]
    assert [record.status for record in records] == [FRAME_USABLE, FRAME_USABLE]

    listing = client.get(f"/api/videos/{upload_id}/occupancy?limit=1")
    assert listing.status_code == status.HTTP_200_OK
    assert listing.json()["total"] == 2
    assert listing.json()["items"][0]["timestamp_seconds"] == 0.0
    assert listing.json()["items"][0]["detections"][0]["class"] == "person"
    evidence_url = listing.json()["items"][0]["evidence_url"]
    assert evidence_url is not None
    evidence = client.get(evidence_url)
    assert evidence.status_code == status.HTTP_200_OK
    assert evidence.headers["content-type"] == "image/jpeg"
    zero_frame = client.get(f"/api/videos/{upload_id}/occupancy?limit=1&offset=1")
    assert zero_frame.status_code == status.HTTP_200_OK
    assert zero_frame.json()["items"][0]["person_count"] == 0
    assert zero_frame.json()["items"][0]["evidence_url"] is not None
    zero_evidence = client.get(zero_frame.json()["items"][0]["evidence_url"])
    assert zero_evidence.status_code == status.HTTP_200_OK
    assert "YOLO person count: 1" in overlay_text
    assert "YOLO person count: 0" in overlay_text


def test_occupancy_api_validation_and_missing_video(client, db_session):
    missing = client.post("/api/videos/not-a-real-upload/occupancy/process")
    assert missing.status_code == status.HTTP_404_NOT_FOUND
    missing_results = client.get("/api/videos/not-a-real-upload/occupancy")
    assert missing_results.status_code == status.HTTP_404_NOT_FOUND

    upload_id = _registered_video(client, db_session, "BATCH-P4-MISS", "ROOM-P4-MISS")
    upload = db_session.query(UploadModel).filter_by(id=upload_id).one()
    (settings.video_upload_dir / upload.stored_filename).unlink()
    response = client.post(f"/api/videos/{upload_id}/occupancy/process")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    non_video = client.post(
        "/api/ingest/attendance",
        files={
            "file": (
                "attendance.csv",
                io.BytesIO(b"batch_id,person_ref,punch_in,punch_out\nB1,P1,2026-10-19 10:00:00,\n"),
                "text/csv",
            )
        },
    )
    non_video_id = non_video.json()["upload"]["id"]
    rejected = client.post(f"/api/videos/{non_video_id}/occupancy/process")
    assert rejected.status_code == status.HTTP_400_BAD_REQUEST


def test_occupancy_requires_quality_assessment(client):
    response = client.post(
        "/api/ingest/video",
        files={"file": ("no-quality.mp4", io.BytesIO(make_dummy_mp4(1024)), "video/mp4")},
        data={
            "batch_id": "BATCH-P4-NOQ",
            "classroom_id": "ROOM-P4-NOQ",
            "recording_date_time": "2026-10-19 10:01:00",
        },
    )
    upload_id = response.json()["upload"]["id"]
    result = client.post(f"/api/videos/{upload_id}/occupancy/process")
    assert result.status_code == status.HTTP_409_CONFLICT


def test_globally_unusable_video_skips_detector_initialization(client, db_session, monkeypatch):
    upload_id = _registered_video(client, db_session, "BATCH-P4-BAD", "ROOM-P4-BAD")
    quality = db_session.query(VideoQualityAssessment).filter_by(upload_id=upload_id).one()
    quality.overall_quality = "UNUSABLE"
    quality.quality_flags = ["LOW_DECODE_RELIABILITY"]
    db_session.commit()
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: FakeCapture([usable_frame()]))

    def detector_must_not_load():
        raise AssertionError("Weights must not be loaded for unusable footage")

    monkeypatch.setattr("app.routes.occupancy.YOLOPersonDetector", detector_must_not_load)

    response = client.post(f"/api/videos/{upload_id}/occupancy/process")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["samples_unusable"] == 1
    row = db_session.query(OccupancyFrame).filter_by(upload_id=upload_id).one()
    assert row.person_count is None
    assert row.status == FRAME_UNUSABLE


def test_inference_failure_persists_null_count(client, db_session, monkeypatch):
    upload_id = _registered_video(client, db_session, "BATCH-P4-ERR", "ROOM-P4-ERR")
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: FakeCapture([usable_frame()]))
    monkeypatch.setattr(
        "app.occupancy_processor.assess_frame_quality",
        lambda _frame: FrameQualityResult(250.0, 120.0, []),
    )
    monkeypatch.setattr(
        "app.routes.occupancy.YOLOPersonDetector",
        lambda: FakeDetector(error="mock failure"),
    )

    response = client.post(f"/api/videos/{upload_id}/occupancy/process")

    assert response.status_code == status.HTTP_200_OK
    row = db_session.query(OccupancyFrame).filter_by(upload_id=upload_id).one()
    assert row.status == "INFERENCE_FAILED"
    assert row.person_count is None


def test_unusable_frame_evidence_endpoint_rejects_image(client, db_session):
    upload_id = _registered_video(client, db_session, "BATCH-P4-EVID", "ROOM-P4-EVID")
    row = OccupancyFrame(
        upload_id=upload_id,
        sample_index=0,
        timestamp_seconds=0.0,
        status=FRAME_UNUSABLE,
        person_count=None,
        detections=[],
        quality_flags=["LOW_LIGHT"],
        evidence_path="should-not-be-served/000000.jpg",
    )
    db_session.add(row)
    db_session.commit()

    response = client.get(f"/api/videos/{upload_id}/occupancy/frames/0/evidence")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "unavailable" in response.json()["detail"].lower()


def test_missing_detector_weights_returns_actionable_service_error(
    client, db_session, monkeypatch
):
    upload_id = _registered_video(client, db_session, "BATCH-P4-WEIGHT", "ROOM-P4-WEIGHT")
    monkeypatch.setattr(
        "app.routes.occupancy.YOLOPersonDetector",
        lambda: (_ for _ in ()).throw(DetectorUnavailableError("weights unavailable")),
    )

    response = client.post(f"/api/videos/{upload_id}/occupancy/process")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "initial YOLO weights download" in response.json()["detail"]


def test_occupancy_migration_is_idempotent_and_preserves_rows():
    engine = create_engine("sqlite://")
    Upload.__table__.create(bind=engine)
    VideoQualityAssessment.__table__.create(bind=engine)
    try:
        factory = sessionmaker(bind=engine)
        with factory.begin() as session:
            session.add(
                Upload(
                    id="existing-upload",
                    upload_type="video",
                    original_filename="existing.mp4",
                    file_size_bytes=10,
                    status="VALIDATED",
                )
            )
        assert migrate_occupancy_frames(engine) is True
        assert migrate_occupancy_frames(engine) is False
        assert "video_quality_samples" in inspect(engine).get_table_names()
        assert "occupancy_frames" in inspect(engine).get_table_names()
        with factory.begin() as session:
            session.add(
                OccupancyFrame(
                    upload_id="existing-upload",
                    sample_index=0,
                    timestamp_seconds=0,
                    status=FRAME_USABLE,
                    person_count=2,
                    detections=[],
                    quality_flags=[],
                )
            )
        with factory() as session:
            assert session.query(Upload).filter_by(id="existing-upload").count() == 1
            assert session.query(OccupancyFrame).one().person_count == 2
    finally:
        engine.dispose()
