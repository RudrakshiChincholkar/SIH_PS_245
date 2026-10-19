import logging
import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Upload, VideoQualityAssessment
from app.schemas import QUALITY_SAFETY_NOTE, VideoProcessResponse, VideoQualityAssessmentResponse
from app.video_processor import VideoProcessingResult, process_video, resolve_stored_video_path

logger = logging.getLogger("attendance_backend.videos")

router = APIRouter(prefix="/api/videos", tags=["Video Quality"])


def _assessment_response(row: VideoQualityAssessment) -> VideoQualityAssessmentResponse:
    flags = row.quality_flags if isinstance(row.quality_flags, list) else []
    return VideoQualityAssessmentResponse(
        upload_id=row.upload_id,
        processing_status=row.processing_status,
        overall_quality=row.overall_quality,
        width=row.width,
        height=row.height,
        fps=row.fps,
        reported_frame_count=row.reported_frame_count,
        duration_seconds=row.duration_seconds,
        sample_interval_seconds=row.sample_interval_seconds,
        samples_attempted=row.samples_attempted,
        samples_successful=row.samples_successful,
        samples_failed=row.samples_failed,
        decode_success_ratio=row.decode_success_ratio,
        avg_blur_score=row.avg_blur_score,
        avg_luminance=row.avg_luminance,
        avg_temporal_difference=row.avg_temporal_difference,
        quality_flags=flags,
        diagnostic_message=row.diagnostic_message,
        analysis_count=row.analysis_count,
        created_at=row.created_at,
        completed_at=row.completed_at,
        safety_note=QUALITY_SAFETY_NOTE,
    )


def _apply_result(
    row: VideoQualityAssessment,
    result: VideoProcessingResult,
    processing_status: str,
) -> None:
    now = datetime.now(timezone.utc)
    row.processing_status = processing_status
    row.overall_quality = result.overall_quality if processing_status == "COMPLETED" else None
    row.width = result.width
    row.height = result.height
    row.fps = result.fps
    row.reported_frame_count = result.reported_frame_count
    row.duration_seconds = result.duration_seconds
    row.sample_interval_seconds = result.sample_interval_seconds
    row.samples_attempted = result.samples_attempted
    row.samples_successful = result.samples_successful
    row.samples_failed = result.samples_failed
    row.decode_success_ratio = result.decode_success_ratio
    row.avg_blur_score = result.avg_blur_score
    row.avg_luminance = result.avg_luminance
    row.avg_temporal_difference = result.avg_temporal_difference
    row.quality_flags = list(result.quality_flags)
    row.diagnostic_message = result.diagnostic_message
    row.completed_at = now
    row.updated_at = now


def _upsert_assessment(
    db: Session,
    upload_id: str,
    interval: float,
) -> VideoQualityAssessment:
    existing = (
        db.query(VideoQualityAssessment)
        .filter(VideoQualityAssessment.upload_id == upload_id)
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing:
        existing.processing_status = "PENDING"
        existing.sample_interval_seconds = interval
        existing.analysis_count = (existing.analysis_count or 0) + 1
        existing.updated_at = now
        return existing

    row = VideoQualityAssessment(
        upload_id=upload_id,
        processing_status="PENDING",
        overall_quality=None,
        sample_interval_seconds=interval,
        samples_attempted=0,
        samples_successful=0,
        samples_failed=0,
        quality_flags=[],
        analysis_count=1,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _parse_sample_interval(sample_interval_seconds: Optional[float]) -> float:
    if sample_interval_seconds is None:
        return float(settings.VIDEO_SAMPLE_INTERVAL_SECONDS)
    if (
        not math.isfinite(sample_interval_seconds)
        or sample_interval_seconds <= 0
        or sample_interval_seconds < settings.VIDEO_SAMPLE_INTERVAL_MIN
        or sample_interval_seconds > settings.VIDEO_SAMPLE_INTERVAL_MAX
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "sample_interval_seconds must be a positive value between "
                f"{settings.VIDEO_SAMPLE_INTERVAL_MIN} and {settings.VIDEO_SAMPLE_INTERVAL_MAX}."
            ),
        )
    return float(sample_interval_seconds)


@router.post("/{upload_id}/process", response_model=VideoProcessResponse)
def process_uploaded_video(
    upload_id: str,
    sample_interval_seconds: Optional[float] = Query(
        None,
        description="Positive sampling interval in seconds (bounded). Defaults to 10.",
    ),
    db: Session = Depends(get_db),
):
    """
    Decode a previously ingested video and persist a footage-quality assessment.

    The file is resolved from the upload database record and verified to live
    inside the configured upload directory. Client filesystem paths are rejected.
    """
    interval = _parse_sample_interval(sample_interval_seconds)

    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload with ID '{upload_id}' not found.",
        )
    if upload.upload_type != "video":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quality analysis is only available for video uploads.",
        )

    try:
        video_path = resolve_stored_video_path(upload.stored_filename or "", settings.video_upload_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    try:
        row = _upsert_assessment(db, upload.id, interval)
        db.flush()

        if not video_path.is_file():
            missing = process_video(video_path, sample_interval_seconds=interval)
            _apply_result(row, missing, processing_status="FAILED")
            db.commit()
            db.refresh(row)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Video file is missing from storage and was not successfully assessed.",
                    "assessment": _assessment_response(row).model_dump(mode="json"),
                },
            )

        result = process_video(video_path, sample_interval_seconds=interval)
        if result.input_missing:
            _apply_result(row, result, processing_status="FAILED")
            db.commit()
            db.refresh(row)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Video file is missing from storage and was not successfully assessed.",
                    "assessment": _assessment_response(row).model_dump(mode="json"),
                },
            )

        _apply_result(row, result, processing_status="COMPLETED")
        db.commit()
        db.refresh(row)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Video quality processing failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process video quality due to an internal server error.",
        )

    quality = row.overall_quality or "UNKNOWN"
    return VideoProcessResponse(
        message=f"Video quality assessment completed with status {quality}.",
        assessment=_assessment_response(row),
    )


@router.get("/{upload_id}/quality", response_model=VideoQualityAssessmentResponse)
def get_video_quality(
    upload_id: str,
    db: Session = Depends(get_db),
):
    """Return the stored quality assessment for a video upload."""
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload with ID '{upload_id}' not found.",
        )

    row = (
        db.query(VideoQualityAssessment)
        .filter(VideoQualityAssessment.upload_id == upload_id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quality assessment for upload '{upload_id}' not found.",
        )
    return _assessment_response(row)
