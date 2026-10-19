"""Incrementally sample a registered recording and persistable person counts."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

import cv2
import numpy as np

from app.person_detector import PersonDetection, filter_and_suppress_detections
from app.video_processor import assess_frame_quality

FRAME_USABLE = "USABLE"
FRAME_UNUSABLE = "UNUSABLE"
FRAME_DECODE_FAILED = "DECODE_FAILED"
FRAME_INFERENCE_FAILED = "INFERENCE_FAILED"


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> List[PersonDetection]: ...


@dataclass
class OccupancyProcessingResult:
    frames: List[Dict[str, Any]] = field(default_factory=list)
    samples_attempted: int = 0
    samples_processed: int = 0
    samples_unusable: int = 0
    samples_failed: int = 0
    diagnostic_message: Optional[str] = None

    @property
    def processing_status(self) -> str:
        if self.samples_failed and self.samples_processed:
            return "PARTIAL"
        if self.samples_failed:
            return "FAILED"
        return "COMPLETED"


def _frame_record(
    upload_id: str,
    sample_index: int,
    timestamp_seconds: float,
    frame_status: str,
    *,
    person_count: Optional[int] = None,
    detections: Optional[List[Dict[str, Any]]] = None,
    quality_flags: Optional[List[str]] = None,
    error_message: Optional[str] = None,
    evidence_path: Optional[str] = None,
) -> Dict[str, Any]:
    detection_rows = detections or []
    confidences = [item["confidence"] for item in detection_rows]
    return {
        "upload_id": upload_id,
        "sample_index": sample_index,
        "timestamp_seconds": timestamp_seconds,
        "status": frame_status,
        "person_count": person_count,
        "mean_confidence": sum(confidences) / len(confidences) if confidences else None,
        "max_confidence": max(confidences) if confidences else None,
        "detections": detection_rows,
        "quality_flags": quality_flags or [],
        "error_message": error_message,
        "evidence_path": evidence_path,
    }


def _draw_evidence(frame: np.ndarray, detections: List[PersonDetection], path: Path) -> bool:
    annotated = frame.copy()
    count_label = f"YOLO person count: {len(detections)}"
    cv2.rectangle(annotated, (8, 8), (260, 38), (0, 0, 0), -1)
    cv2.putText(
        annotated,
        count_label,
        (14, 29),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    for detection in detections:
        x1, y1, x2, y2 = (int(round(value)) for value in detection.box)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (40, 190, 70), 2)
        cv2.putText(
            annotated,
            f"person {detection.confidence:.2f}",
            (x1, max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (40, 190, 70),
            1,
            cv2.LINE_AA,
        )
    return bool(cv2.imwrite(str(path), annotated))


def process_occupancy_video(
    video_path: Path,
    upload_id: str,
    sample_interval_seconds: float,
    detector: Detector,
    *,
    globally_unusable: bool = False,
    global_quality_flags: Optional[List[str]] = None,
    evidence_enabled: bool = False,
    evidence_dir: Optional[Path] = None,
    max_evidence_frames: int = 20,
    evidence_run_id: Optional[str] = None,
    stored_quality_samples: Optional[Dict[int, Dict[str, Any]]] = None,
    frame_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> OccupancyProcessingResult:
    """Read one frame at a time and count only samples passing frame-quality checks."""
    if not math.isfinite(sample_interval_seconds) or sample_interval_seconds <= 0:
        raise ValueError("sample_interval_seconds must be finite and positive")

    result = OccupancyProcessingResult()
    cap = None
    evidence_count = 0
    frames_emitted = 0
    evidence_run_id = evidence_run_id or str(uuid.uuid4())
    evidence_root = Path(evidence_dir).resolve() if evidence_dir else None
    capture_opened = False

    def emit(frame_result: Dict[str, Any]) -> None:
        nonlocal frames_emitted
        frames_emitted += 1
        if frame_callback is None:
            result.frames.append(frame_result)
        else:
            frame_callback(frame_result)

    try:
        cap = cv2.VideoCapture(str(video_path))
        capture_opened = bool(cap is not None and cap.isOpened())
        if not capture_opened:
            result.samples_attempted = 1
            result.samples_failed = 1
            emit(
                _frame_record(
                    upload_id,
                    0,
                    0.0,
                    FRAME_DECODE_FAILED,
                    quality_flags=["DECODE_FAILURE"],
                    error_message="OpenCV could not open the registered video or its codec is unsupported.",
                )
            )
            result.diagnostic_message = "No frames could be decoded from the registered video."
            return result

        raw_fps = float(cap.get(cv2.CAP_PROP_FPS))
        fps = raw_fps if math.isfinite(raw_fps) and raw_fps > 0 else None
        if fps is None:
            result.samples_attempted = 1
            result.samples_unusable = 1
            emit(
                _frame_record(
                    upload_id,
                    0,
                    0.0,
                    FRAME_UNUSABLE,
                    quality_flags=["INVALID_VIDEO_METADATA"],
                    error_message="A valid FPS value is required to align quality and occupancy samples.",
                )
            )
            result.diagnostic_message = "Occupancy samples were skipped because frame timing metadata is invalid."
            return result

        next_sample_seconds = 0.0
        frame_index = 0
        sample_index = 0
        while True:
            success, frame = cap.read()
            if not success:
                reported_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if math.isfinite(reported_count) and frame_index < reported_count:
                    result.samples_attempted += 1
                    result.samples_failed += 1
                    emit(
                        _frame_record(
                            upload_id,
                            sample_index,
                            next_sample_seconds,
                            FRAME_DECODE_FAILED,
                            quality_flags=["DECODE_FAILURE"],
                            error_message="Video decoding stopped before the reported end of the recording.",
                        )
                    )
                break

            timestamp_seconds = frame_index / fps
            if timestamp_seconds + 1e-9 >= next_sample_seconds:
                result.samples_attempted += 1
                saved_quality = (stored_quality_samples or {}).get(sample_index)
                sample_timestamp = (
                    float(saved_quality["timestamp_seconds"])
                    if saved_quality is not None
                    else timestamp_seconds
                )
                if globally_unusable:
                    result.samples_unusable += 1
                    emit(
                        _frame_record(
                            upload_id,
                            sample_index,
                            sample_timestamp,
                            FRAME_UNUSABLE,
                            quality_flags=list(global_quality_flags or ["UNUSABLE_VIDEO_QUALITY"]),
                            error_message="The Part 3 video assessment classified this recording as unusable.",
                        )
                    )
                elif saved_quality is not None and saved_quality["status"] == "DECODE_FAILED":
                    result.samples_failed += 1
                    emit(
                        _frame_record(
                            upload_id,
                            sample_index,
                            sample_timestamp,
                            FRAME_DECODE_FAILED,
                            quality_flags=list(saved_quality.get("quality_flags") or ["DECODE_FAILURE"]),
                            error_message="Part 3 could not decode this sampled frame.",
                        )
                    )
                elif saved_quality is not None and saved_quality["status"] == "UNUSABLE":
                    result.samples_unusable += 1
                    emit(
                        _frame_record(
                            upload_id,
                            sample_index,
                            sample_timestamp,
                            FRAME_UNUSABLE,
                            quality_flags=list(saved_quality.get("quality_flags") or []),
                            error_message="Part 3 marked this sampled frame unusable; no count was produced.",
                        )
                    )
                else:
                    try:
                        frame_quality = assess_frame_quality(frame)
                    except Exception as exc:
                        frame_quality = None
                        quality_error = str(exc)
                    else:
                        quality_error = None

                    if frame_quality is None:
                        result.samples_unusable += 1
                        emit(
                            _frame_record(
                                upload_id,
                                sample_index,
                                sample_timestamp,
                                FRAME_UNUSABLE,
                                quality_flags=["FRAME_QUALITY_FAILED"],
                                error_message=quality_error,
                            )
                        )
                    elif not frame_quality.usable:
                        result.samples_unusable += 1
                        emit(
                            _frame_record(
                                upload_id,
                                sample_index,
                                sample_timestamp,
                                FRAME_UNUSABLE,
                                quality_flags=frame_quality.flags,
                                error_message="Frame failed the Part 3 legibility thresholds; no count was produced.",
                            )
                        )
                    else:
                        try:
                            raw_detections = detector.detect(frame)
                            detections = filter_and_suppress_detections(
                                raw_detections,
                                detector.confidence_threshold
                                if hasattr(detector, "confidence_threshold")
                                else 0.25,
                                detector.iou_threshold
                                if hasattr(detector, "iou_threshold")
                                else 0.45,
                            )
                            serialized = [
                                {
                                    "box": [float(value) for value in item.box],
                                    "confidence": float(item.confidence),
                                    "class": "person",
                                }
                                for item in detections
                            ]
                            relative_evidence = None
                            if (
                                evidence_enabled
                                and evidence_root is not None
                                and evidence_count < max_evidence_frames
                            ):
                                frame_dir = (evidence_root / upload_id / evidence_run_id).resolve()
                                frame_dir.relative_to(evidence_root)
                                frame_dir.mkdir(parents=True, exist_ok=True)
                                evidence_file = frame_dir / f"{sample_index:06d}.jpg"
                                if _draw_evidence(frame, detections, evidence_file):
                                    relative_evidence = (
                                        f"{upload_id}/{evidence_run_id}/{evidence_file.name}"
                                    )
                                    evidence_count += 1
                            result.samples_processed += 1
                            emit(
                                _frame_record(
                                    upload_id,
                                    sample_index,
                                    sample_timestamp,
                                    FRAME_USABLE,
                                    person_count=len(serialized),
                                    detections=serialized,
                                    evidence_path=relative_evidence,
                                )
                            )
                        except Exception as exc:
                            result.samples_failed += 1
                            emit(
                                _frame_record(
                                    upload_id,
                                    sample_index,
                                    sample_timestamp,
                                    FRAME_INFERENCE_FAILED,
                                    quality_flags=[],
                                    error_message=f"Person inference failed for this frame: {exc}",
                                )
                            )

                sample_index += 1
                next_sample_seconds += sample_interval_seconds

            del frame
            frame_index += 1

        if not result.frames and result.samples_attempted == 0:
            result.samples_attempted = 1
            result.samples_failed = 1
            emit(
                _frame_record(
                    upload_id,
                    0,
                    0.0,
                    FRAME_DECODE_FAILED,
                    quality_flags=["DECODE_FAILURE"],
                    error_message="The video opened but contained no decodable frames.",
                )
            )

        if result.samples_failed and result.samples_processed:
            result.diagnostic_message = (
                "Some sampled frames failed decoding or person inference; successful frame results were retained."
            )
        elif result.samples_failed:
            result.diagnostic_message = (
                "All attempted samples failed decoding or person inference; no valid person counts are available."
            )
        elif result.samples_attempted and result.samples_unusable == result.samples_attempted:
            result.diagnostic_message = (
                "No counts were produced because every sampled frame was unusable under the video-quality checks."
            )
        elif frames_emitted == 0:
            result.diagnostic_message = "The video opened but yielded no decodable frames."
        else:
            result.diagnostic_message = "Frame-level person counts completed for usable sampled frames."
        return result
    finally:
        if cap is not None:
            cap.release()
