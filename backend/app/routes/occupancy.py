"""Frame-level person counts for registered CCTV videos (Part 4)."""

from __future__ import annotations

import logging
import uuid
from typing import Dict, Any, List
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import OccupancyFrame, Upload, VideoQualityAssessment, VideoQualitySample
from app.occupancy_processor import process_occupancy_video
from app.person_detector import DetectorUnavailableError, YOLOPersonDetector
from app.schemas import (
    OccupancyFrameListResponse,
    OccupancyFrameResponse,
    OccupancyProcessResponse,
)
from app.video_processor import resolve_stored_video_path

logger = logging.getLogger("attendance_backend.occupancy")
router = APIRouter(prefix="/api/videos", tags=["Occupancy Counts"])


def _frame_response(row: OccupancyFrame) -> OccupancyFrameResponse:
    evidence_url = None
    if row.evidence_path:
        evidence_url = (
            f"/api/videos/{row.upload_id}/occupancy/frames/"
            f"{row.sample_index}/evidence"
        )
    return OccupancyFrameResponse(
        id=row.id,
        upload_id=row.upload_id,
        sample_index=row.sample_index,
        timestamp_seconds=row.timestamp_seconds,
        status=row.status,
        person_count=row.person_count,
        mean_confidence=row.mean_confidence,
        max_confidence=row.max_confidence,
        detections=row.detections if isinstance(row.detections, list) else [],
        quality_flags=row.quality_flags if isinstance(row.quality_flags, list) else [],
        error_message=row.error_message,
        evidence_url=evidence_url,
        created_at=row.created_at,
    )


def _cleanup_new_evidence(result, evidence_dir: Optional[Path]) -> None:
    if evidence_dir is None:
        return
    root = evidence_dir.resolve()
    for row in result.frames:
        relative = row.get("evidence_path")
        if not relative:
            continue
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        path.unlink(missing_ok=True)


@router.post(
    "/{upload_id}/occupancy/process",
    response_model=OccupancyProcessResponse,
)
def process_video_occupancy(upload_id: str, db: Session = Depends(get_db)):
    """Count COCO person detections at the completed Part 3 sample timestamps."""
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if upload is None:
        raise HTTPException(status_code=404, detail="Video upload was not found.")
    if upload.upload_type != "video":
        raise HTTPException(status_code=400, detail="Occupancy processing requires a video upload.")

    quality = (
        db.query(VideoQualityAssessment)
        .filter(VideoQualityAssessment.upload_id == upload_id)
        .first()
    )
    if quality is None:
        raise HTTPException(
            status_code=409,
            detail="Run the video quality assessment before person counting.",
        )
    if quality.processing_status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail="The video quality assessment did not complete successfully; occupancy processing was not started.",
        )

    try:
        video_path = resolve_stored_video_path(
            upload.stored_filename or "",
            settings.video_upload_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not video_path.is_file():
        raise HTTPException(
            status_code=422,
            detail="The registered video file is missing from storage; no occupancy counts were produced.",
        )

    global_flags = quality.quality_flags if isinstance(quality.quality_flags, list) else []
    globally_unusable = quality.overall_quality == "UNUSABLE"
    detector = None
    if not globally_unusable:
        try:
            detector = YOLOPersonDetector()
        except Exception as exc:
            logger.warning("Person detector initialization failed: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=(
                    "The CPU person detector is unavailable. Install backend requirements and "
                    "allow the initial YOLO weights download, or configure a local model path."
                ),
            ) from exc
    upload_root = Path(settings.UPLOAD_DIR)
    if not upload_root.is_absolute():
        upload_root = settings.base_dir / upload_root
    evidence_dir = (
        upload_root / "occupancy-evidence"
        if settings.OCCUPANCY_EVIDENCE_ENABLED
        else None
    )
    evidence_run_id = str(uuid.uuid4())
    quality_samples = {
        sample.sample_index: {
            "timestamp_seconds": sample.timestamp_seconds,
            "status": sample.status,
            "quality_flags": sample.quality_flags,
        }
        for sample in db.query(VideoQualitySample)
        .filter(VideoQualitySample.upload_id == upload_id)
        .all()
    }
    new_evidence_paths = set()
    try:
        db.query(OccupancyFrame).filter(OccupancyFrame.upload_id == upload_id).delete(
            synchronize_session=False
        )
        pending_rows: List[Dict[str, Any]] = []

        def persist_frame(frame: Dict[str, Any]) -> None:
            if frame.get("evidence_path"):
                new_evidence_paths.add(frame["evidence_path"])
            pending_rows.append(frame)
            if len(pending_rows) >= 200:
                db.execute(OccupancyFrame.__table__.insert(), pending_rows)
                pending_rows.clear()

        result = process_occupancy_video(
            video_path,
            upload_id,
            float(quality.sample_interval_seconds),
            detector,
            globally_unusable=globally_unusable,
            global_quality_flags=global_flags,
            evidence_enabled=settings.OCCUPANCY_EVIDENCE_ENABLED,
            evidence_dir=evidence_dir,
            max_evidence_frames=settings.OCCUPANCY_EVIDENCE_MAX_FRAMES,
            evidence_run_id=evidence_run_id,
            stored_quality_samples=quality_samples,
            frame_callback=persist_frame,
        )
        previous_paths = [
            row.evidence_path
            for row in db.query(OccupancyFrame.evidence_path)
            .filter(OccupancyFrame.upload_id == upload_id)
            .all()
            if row[0]
        ]
        if pending_rows:
            db.execute(OccupancyFrame.__table__.insert(), pending_rows)
        db.commit()
    except Exception as exc:
        db.rollback()
        _cleanup_new_evidence(
            {"frames": [{"evidence_path": path} for path in new_evidence_paths]},
            evidence_dir,
        )
        logger.exception("Occupancy processing failed for upload %s", upload_id)
        raise HTTPException(
            status_code=500,
            detail="Occupancy processing could not be saved. Retry after checking backend logs and database connectivity.",
        ) from exc

    new_paths = new_evidence_paths
    if evidence_dir is not None:
        root = evidence_dir.resolve()
        for relative in previous_paths:
            if relative in new_paths:
                continue
            old_path = (root / relative).resolve()
            try:
                old_path.relative_to(root)
            except ValueError:
                continue
            old_path.unlink(missing_ok=True)

    return OccupancyProcessResponse(
        message=result.diagnostic_message or "Frame-level person counts completed.",
        upload_id=upload_id,
        processing_status=result.processing_status,
        detector_model=settings.PERSON_DETECTOR_MODEL,
        sample_interval_seconds=float(quality.sample_interval_seconds),
        samples_attempted=result.samples_attempted,
        samples_processed=result.samples_processed,
        samples_unusable=result.samples_unusable,
        samples_failed=result.samples_failed,
    )


@router.get(
    "/{upload_id}/occupancy",
    response_model=OccupancyFrameListResponse,
)
def get_video_occupancy_frames(
    upload_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if upload is None:
        raise HTTPException(status_code=404, detail="Video upload was not found.")
    total = db.query(OccupancyFrame).filter(OccupancyFrame.upload_id == upload_id).count()
    if total == 0:
        raise HTTPException(
            status_code=404,
            detail="No occupancy results exist for this video; run occupancy processing first.",
        )
    rows = (
        db.query(OccupancyFrame)
        .filter(OccupancyFrame.upload_id == upload_id)
        .order_by(OccupancyFrame.sample_index)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return OccupancyFrameListResponse(
        upload_id=upload_id,
        items=[_frame_response(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{upload_id}/occupancy/frames/{sample_index}/evidence",
    response_class=FileResponse,
)
def get_occupancy_frame_evidence(
    upload_id: str,
    sample_index: int,
    db: Session = Depends(get_db),
):
    row = (
        db.query(OccupancyFrame)
        .filter(
            OccupancyFrame.upload_id == upload_id,
            OccupancyFrame.sample_index == sample_index,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Occupancy frame was not found.")
    if row.status != "USABLE" or row.person_count is None or not row.evidence_path:
        raise HTTPException(
            status_code=404,
            detail="Annotated evidence is unavailable for this frame.",
        )
    root = settings.occupancy_evidence_dir.resolve()
    evidence_path = (root / row.evidence_path).resolve()
    try:
        evidence_path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Evidence file was not found.") from exc
    if not evidence_path.is_file():
        raise HTTPException(status_code=404, detail="Evidence file was not found.")
    return FileResponse(evidence_path, media_type="image/jpeg")
