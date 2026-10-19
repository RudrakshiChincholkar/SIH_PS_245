"""
Recorded-video decoding and footage-legibility assessment (Part 3).

This module samples frames at a configurable time interval, computes cheap
image-quality heuristics, and classifies footage as USABLE, DEGRADED, or
UNUSABLE. It does not detect people, estimate occupancy, recognize faces,
or reconcile attendance.

Limitations of the heuristics (not camera-certification standards):
- Metrics are computed on a consistently resized grayscale view (default
  320x180). Laplacian variance is resolution- and content-dependent; a
  flat wall, empty whiteboard, or low-texture scene can look "blurry"
  without an out-of-focus lens. A flat gradient alone is not treated as
  proof of blur.
- Mean luminance is a global grayscale average. Mixed lighting, IR night
  mode, and auto-exposure can mis-trigger LOW_LIGHT or OVEREXPOSURE.
- Mean absolute difference between temporal samples can be low in a
  genuinely static classroom. POSSIBLE_FROZEN_FOOTAGE is recorded only
  when several consecutive sample pairs are near-identical; a single
  identical pair is never enough.
- OpenCV-reported FPS, frame count, and duration are container metadata
  and can be wrong or unavailable depending on codec.
- Failed, dark, blurred, frozen, or unreadable footage means the system
  lacks reliable visual evidence. It must never be interpreted as zero
  people in the classroom.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import cv2
import numpy as np
from app.config import settings

# Analysis canvas — all comparisons use this grayscale size.
ANALYSIS_WIDTH = 320
ANALYSIS_HEIGHT = 180

# Preliminary quality thresholds (documented, configurable).
BLUR_LAPLACIAN_THRESHOLD = settings.VIDEO_QUALITY_BLUR_THRESHOLD
LOW_LIGHT_LUMINANCE_THRESHOLD = settings.VIDEO_QUALITY_LOW_LIGHT_THRESHOLD
OVEREXPOSURE_LUMINANCE_THRESHOLD = settings.VIDEO_QUALITY_OVEREXPOSURE_THRESHOLD
NEAR_IDENTICAL_MAD_THRESHOLD = settings.VIDEO_QUALITY_NEAR_IDENTICAL_MAD_THRESHOLD
MIN_DECODE_SUCCESS_RATIO = settings.VIDEO_QUALITY_MIN_DECODE_SUCCESS_RATIO
BLACK_LUMINANCE_THRESHOLD = settings.VIDEO_QUALITY_BLACK_LUMINANCE_THRESHOLD

# Conservative frozen-footage rule: require several near-identical pairs,
# not a single static classroom snapshot.
FROZEN_MIN_IDENTICAL_PAIRS = settings.VIDEO_QUALITY_FROZEN_MIN_IDENTICAL_PAIRS
FROZEN_IDENTICAL_PAIR_RATIO = settings.VIDEO_QUALITY_FROZEN_IDENTICAL_PAIR_RATIO

OCCUPANCY_SAFETY_NOTE = (
    "Quality assessment measures footage legibility only. "
    "It does not count people or infer zero occupancy."
)

QUALITY_USABLE = "USABLE"
QUALITY_DEGRADED = "DEGRADED"
QUALITY_UNUSABLE = "UNUSABLE"

FLAG_POTENTIAL_BLUR = "POTENTIAL_BLUR"
FLAG_LOW_LIGHT = "LOW_LIGHT"
FLAG_OVEREXPOSURE = "OVEREXPOSURE"
FLAG_POSSIBLE_FROZEN_FOOTAGE = "POSSIBLE_FROZEN_FOOTAGE"
FLAG_LOW_DECODE_RELIABILITY = "LOW_DECODE_RELIABILITY"
FLAG_DECODE_FAILURE = "DECODE_FAILURE"
FLAG_INVALID_METADATA = "INVALID_VIDEO_METADATA"
FLAG_COMPLETELY_BLACK = "COMPLETELY_BLACK"
FLAG_UNREADABLE = "UNREADABLE"


@dataclass
class VideoProcessingResult:
    """Structured quality result. Never includes filesystem paths."""

    input_missing: bool
    capture_opened: bool
    overall_quality: Optional[str]
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    reported_frame_count: Optional[int]
    duration_seconds: Optional[float]
    sample_interval_seconds: float
    samples_attempted: int
    samples_successful: int
    samples_failed: int
    decode_success_ratio: Optional[float]
    avg_blur_score: Optional[float]
    avg_luminance: Optional[float]
    avg_temporal_difference: Optional[float]
    quality_flags: List[str] = field(default_factory=list)
    diagnostic_message: str = ""


@dataclass
class FrameQualityResult:
    blur_score: float
    luminance: float
    flags: List[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.flags


def resolve_stored_video_path(stored_filename: str, upload_dir: Path) -> Path:
    """
    Resolve a video path from the upload record's stored filename only.

    Client-supplied filesystem paths are never accepted. The resolved path
    must remain inside the configured upload directory after normalization.
    """
    if not stored_filename or not str(stored_filename).strip():
        raise ValueError("Upload record does not include a stored filename.")

    name = Path(str(stored_filename)).name
    if name != str(stored_filename) or name in {".", ".."}:
        raise ValueError("Stored filename is not a simple basename.")

    base = Path(upload_dir).resolve()
    candidate = (base / name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("Resolved video path is outside the upload directory.") from exc
    return candidate


def _finite_positive(value: float) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _to_analysis_gray(frame: np.ndarray) -> np.ndarray:
    if frame is None or frame.size == 0:
        raise ValueError("Empty frame")
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    elif frame.ndim == 2:
        gray = frame
    else:
        raise ValueError("Unsupported frame layout")
    return cv2.resize(gray, (ANALYSIS_WIDTH, ANALYSIS_HEIGHT), interpolation=cv2.INTER_AREA)


def _mean_abs_diff(prev_gray: np.ndarray, gray: np.ndarray) -> float:
    diff = cv2.absdiff(prev_gray, gray)
    return float(np.mean(diff.astype(np.float32)))


def assess_frame_quality(frame: np.ndarray) -> FrameQualityResult:
    """Apply Part 3's per-frame legibility thresholds to one decoded frame."""
    gray = _to_analysis_gray(frame)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    luminance = float(np.mean(gray.astype(np.float32)))
    flags: List[str] = []
    if blur_score < BLUR_LAPLACIAN_THRESHOLD:
        flags.append(FLAG_POTENTIAL_BLUR)
    if luminance < LOW_LIGHT_LUMINANCE_THRESHOLD:
        flags.append(FLAG_LOW_LIGHT)
    if luminance > OVEREXPOSURE_LUMINANCE_THRESHOLD:
        flags.append(FLAG_OVEREXPOSURE)
    if luminance <= BLACK_LUMINANCE_THRESHOLD:
        flags.append(FLAG_COMPLETELY_BLACK)
    return FrameQualityResult(blur_score, luminance, flags)


def _unusable_result(
    sample_interval_seconds: float,
    *,
    input_missing: bool = False,
    capture_opened: bool = False,
    width: Optional[int] = None,
    height: Optional[int] = None,
    fps: Optional[float] = None,
    reported_frame_count: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    samples_attempted: int = 0,
    samples_successful: int = 0,
    samples_failed: int = 0,
    flags: Optional[Sequence[str]] = None,
    diagnostic: str = "",
) -> VideoProcessingResult:
    attempted = samples_attempted
    ratio = (samples_successful / attempted) if attempted else 0.0
    flag_list = list(flags or [])
    if FLAG_UNREADABLE not in flag_list:
        flag_list.append(FLAG_UNREADABLE)
    if (
        attempted > 0
        and ratio < MIN_DECODE_SUCCESS_RATIO
        and FLAG_LOW_DECODE_RELIABILITY not in flag_list
    ):
        flag_list.append(FLAG_LOW_DECODE_RELIABILITY)
    message = diagnostic.strip()
    if OCCUPANCY_SAFETY_NOTE not in message:
        message = f"{message} {OCCUPANCY_SAFETY_NOTE}".strip()
    return VideoProcessingResult(
        input_missing=input_missing,
        capture_opened=capture_opened,
        overall_quality=QUALITY_UNUSABLE,
        width=width,
        height=height,
        fps=fps,
        reported_frame_count=reported_frame_count,
        duration_seconds=duration_seconds,
        sample_interval_seconds=sample_interval_seconds,
        samples_attempted=samples_attempted,
        samples_successful=samples_successful,
        samples_failed=samples_failed,
        decode_success_ratio=ratio,
        avg_blur_score=None,
        avg_luminance=None,
        avg_temporal_difference=None,
        quality_flags=flag_list,
        diagnostic_message=message,
    )


def classify_from_metrics(
    *,
    capture_opened: bool,
    samples_attempted: int,
    samples_successful: int,
    avg_blur_score: Optional[float],
    avg_luminance: Optional[float],
    identical_pairs: int,
    temporal_pairs: int,
    decode_success_ratio: Optional[float],
    samples_failed: int = 0,
    invalid_timing_metadata: bool = False,
) -> tuple[str, List[str], str]:
    """Apply documented quality rules. Occupancy is never inferred."""
    flags: List[str] = []

    if not capture_opened or samples_successful <= 0:
        flags.append(FLAG_UNREADABLE)
        if samples_attempted > 0 and (decode_success_ratio or 0.0) < MIN_DECODE_SUCCESS_RATIO:
            flags.append(FLAG_LOW_DECODE_RELIABILITY)
        return (
            QUALITY_UNUSABLE,
            flags,
            "No usable decoded frames were obtained. Footage is unreadable or corrupt. "
            + OCCUPANCY_SAFETY_NOTE,
        )

    if avg_luminance is not None and avg_luminance <= BLACK_LUMINANCE_THRESHOLD:
        flags.append(FLAG_COMPLETELY_BLACK)
        return (
            QUALITY_UNUSABLE,
            flags,
            "Footage is completely black (mean luminance at or below the configured threshold). "
            + OCCUPANCY_SAFETY_NOTE,
        )

    if avg_blur_score is not None and avg_blur_score < BLUR_LAPLACIAN_THRESHOLD:
        flags.append(FLAG_POTENTIAL_BLUR)
    if avg_luminance is not None and avg_luminance < LOW_LIGHT_LUMINANCE_THRESHOLD:
        flags.append(FLAG_LOW_LIGHT)
    if avg_luminance is not None and avg_luminance > OVEREXPOSURE_LUMINANCE_THRESHOLD:
        flags.append(FLAG_OVEREXPOSURE)

    if (
        temporal_pairs >= FROZEN_MIN_IDENTICAL_PAIRS
        and identical_pairs >= FROZEN_MIN_IDENTICAL_PAIRS
        and (identical_pairs / temporal_pairs) >= FROZEN_IDENTICAL_PAIR_RATIO
    ):
        flags.append(FLAG_POSSIBLE_FROZEN_FOOTAGE)

    if decode_success_ratio is not None and decode_success_ratio < MIN_DECODE_SUCCESS_RATIO:
        flags.append(FLAG_LOW_DECODE_RELIABILITY)
    if samples_failed > 0:
        flags.append(FLAG_DECODE_FAILURE)
    if invalid_timing_metadata:
        flags.append(FLAG_INVALID_METADATA)

    if flags:
        quality = QUALITY_DEGRADED
        diagnostic = (
            "Footage decoded but one or more quality heuristics were triggered: "
            + ", ".join(flags)
            + ". These are preliminary legibility flags, not occupancy counts. "
            + OCCUPANCY_SAFETY_NOTE
        )
    else:
        quality = QUALITY_USABLE
        diagnostic = (
            "Sampled frames decoded with sharpness, luminance, temporal variation, "
            "and decode reliability within configured heuristic bounds. "
            + OCCUPANCY_SAFETY_NOTE
        )

    return quality, flags, diagnostic


def process_video(
    video_path: Path,
    sample_interval_seconds: float = 10.0,
    sample_callback: Optional[Callable[[Dict[str, object]], None]] = None,
) -> VideoProcessingResult:
    """
    Decode a recording incrementally and sample frames on a time grid.

    Only the current decoded frame and the previous analysis-size grayscale
    sample are retained. The full recording is never loaded into RAM.
    OpenCV capture resources are always released.
    """
    if sample_interval_seconds <= 0:
        raise ValueError("sample_interval_seconds must be positive.")

    path = Path(video_path)
    if not path.exists() or not path.is_file():
        return _unusable_result(
            sample_interval_seconds,
            input_missing=True,
            diagnostic="Video file is missing from storage and was not assessed.",
        )

    cap = None
    width = height = None
    fps: Optional[float] = None
    reported_frame_count: Optional[int] = None
    duration_seconds: Optional[float] = None
    samples_attempted = 0
    samples_successful = 0
    samples_failed = 0
    blur_score_sum = 0.0
    luminance_sum = 0.0
    temporal_difference_sum = 0.0
    temporal_difference_count = 0
    identical_pairs = 0
    temporal_pairs = 0
    prev_gray: Optional[np.ndarray] = None
    decoded_frames = 0
    capture_opened = False
    invalid_timing_metadata = False
    sample_index = 0

    try:
        cap = cv2.VideoCapture(str(path))
        capture_opened = bool(cap is not None and cap.isOpened())
        if not capture_opened:
            if sample_callback:
                sample_callback({
                    "sample_index": 0,
                    "timestamp_seconds": 0.0,
                    "status": "DECODE_FAILED",
                    "blur_score": None,
                    "luminance": None,
                    "quality_flags": [FLAG_DECODE_FAILURE],
                })
            return _unusable_result(
                sample_interval_seconds,
                capture_opened=False,
                samples_attempted=1,
                samples_failed=1,
                flags=[FLAG_DECODE_FAILURE],
                diagnostic="OpenCV could not open the file (corrupt container or unsupported codec).",
            )

        raw_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        raw_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        raw_fps = cap.get(cv2.CAP_PROP_FPS)
        raw_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)

        width = int(raw_w) if raw_w and raw_w > 0 else None
        height = int(raw_h) if raw_h and raw_h > 0 else None
        fps = _finite_positive(raw_fps)
        invalid_timing_metadata = fps is None
        if raw_count is not None and math.isfinite(float(raw_count)) and raw_count >= 0:
            reported_frame_count = int(raw_count)
        if fps and reported_frame_count and reported_frame_count > 0:
            duration_seconds = reported_frame_count / fps

        next_sample_t = 0.0
        frame_index = 0

        while True:
            ok, frame = cap.read()
            if not ok:
                # A failed read before the reported end is a decode failure,
                # not normal EOF. Record the failed decode as an attempted sample.
                if reported_frame_count is not None and frame_index < reported_frame_count:
                    samples_attempted += 1
                    samples_failed += 1
                    if sample_callback:
                        sample_callback({
                            "sample_index": sample_index,
                            "timestamp_seconds": frame_index / fps if fps else next_sample_t,
                            "status": "DECODE_FAILED",
                            "blur_score": None,
                            "luminance": None,
                            "quality_flags": [FLAG_DECODE_FAILURE],
                        })
                break
            decoded_frames += 1

            timestamp = frame_index / fps if fps else 0.0
            sample_due = (
                timestamp + 1e-9 >= next_sample_t
                if fps
                else samples_attempted == 0
            )
            if sample_due:
                samples_attempted += 1
                try:
                    frame_quality = assess_frame_quality(frame)
                    gray = _to_analysis_gray(frame)
                    blur = frame_quality.blur_score
                    lum = frame_quality.luminance
                    if prev_gray is not None:
                        temporal_pairs += 1
                        mad = _mean_abs_diff(prev_gray, gray)
                        temporal_difference_sum += mad
                        temporal_difference_count += 1
                        if mad < NEAR_IDENTICAL_MAD_THRESHOLD:
                            identical_pairs += 1
                    prev_gray = gray
                    blur_score_sum += blur
                    luminance_sum += lum
                    samples_successful += 1
                    if sample_callback:
                        sample_callback({
                            "sample_index": sample_index,
                            "timestamp_seconds": timestamp,
                            "status": "USABLE" if frame_quality.usable else "UNUSABLE",
                            "blur_score": blur,
                            "luminance": lum,
                            "quality_flags": list(frame_quality.flags),
                        })
                except Exception:
                    samples_failed += 1
                    if sample_callback:
                        sample_callback({
                            "sample_index": sample_index,
                            "timestamp_seconds": timestamp,
                            "status": "DECODE_FAILED",
                            "blur_score": None,
                            "luminance": None,
                            "quality_flags": [FLAG_DECODE_FAILURE],
                        })
                sample_index += 1
                next_sample_t += sample_interval_seconds

            # Drop the BGR frame immediately; only prev_gray is retained.
            del frame
            frame_index += 1

        if decoded_frames == 0:
            if sample_callback and sample_index == 0 and not reported_frame_count:
                sample_callback({
                    "sample_index": 0,
                    "timestamp_seconds": 0.0,
                    "status": "DECODE_FAILED",
                    "blur_score": None,
                    "luminance": None,
                    "quality_flags": [FLAG_DECODE_FAILURE],
                })
            return _unusable_result(
                sample_interval_seconds,
                capture_opened=True,
                width=width,
                height=height,
                fps=fps,
                reported_frame_count=reported_frame_count,
                duration_seconds=duration_seconds,
                samples_attempted=1 if reported_frame_count and reported_frame_count > 0 else 0,
                samples_failed=1 if reported_frame_count and reported_frame_count > 0 else 0,
                flags=[FLAG_DECODE_FAILURE] if reported_frame_count and reported_frame_count > 0 else [],
                diagnostic="The container opened but zero frames could be decoded.",
            )

        if duration_seconds is None and fps:
            duration_seconds = decoded_frames / fps

        decode_success_ratio = (
            samples_successful / samples_attempted if samples_attempted else 0.0
        )
        avg_blur = blur_score_sum / samples_successful if samples_successful else None
        avg_lum = luminance_sum / samples_successful if samples_successful else None
        avg_temporal_difference = (
            temporal_difference_sum / temporal_difference_count
            if temporal_difference_count
            else None
        )

        quality, flags, diagnostic = classify_from_metrics(
            capture_opened=True,
            samples_attempted=samples_attempted,
            samples_successful=samples_successful,
            avg_blur_score=avg_blur,
            avg_luminance=avg_lum,
            identical_pairs=identical_pairs,
            temporal_pairs=temporal_pairs,
            decode_success_ratio=decode_success_ratio,
            samples_failed=samples_failed,
            invalid_timing_metadata=invalid_timing_metadata,
        )

        return VideoProcessingResult(
            input_missing=False,
            capture_opened=True,
            overall_quality=quality,
            width=width,
            height=height,
            fps=fps,
            reported_frame_count=reported_frame_count,
            duration_seconds=duration_seconds,
            sample_interval_seconds=sample_interval_seconds,
            samples_attempted=samples_attempted,
            samples_successful=samples_successful,
            samples_failed=samples_failed,
            decode_success_ratio=decode_success_ratio,
            avg_blur_score=avg_blur,
            avg_luminance=avg_lum,
            avg_temporal_difference=avg_temporal_difference,
            quality_flags=flags,
            diagnostic_message=diagnostic,
        )
    finally:
        if cap is not None:
            cap.release()
