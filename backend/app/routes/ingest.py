import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    File,
    Form,
    HTTPException,
    Query,
    status,
    Response,
)
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import get_db
from app.models import Upload, VideoMetadata, AttendanceRecord, ScheduleRecord
from app.schemas import (
    UploadResponse,
    UploadDetailResponse,
    UploadListResponse,
    VideoUploadResponse,
    AttendanceUploadResponse,
    ScheduleUploadResponse,
    VideoMetadataResponse,
)
from app.validators import (
    stream_and_validate_video,
    validate_attendance_csv_content,
    validate_schedule_csv_content,
    parse_and_normalize_timestamp,
)

logger = logging.getLogger("attendance_backend.ingest")

router = APIRouter(prefix="/api/ingest", tags=["Input Ingestion"])


@router.post("/video", response_model=VideoUploadResponse, status_code=status.HTTP_201_CREATED)
async def ingest_video(
    file: UploadFile = File(..., description="CCTV video file (.mp4, .avi, .mov)"),
    batch_id: str = Form(..., description="Training centre batch ID"),
    classroom_id: str = Form(..., description="Classroom or training hall ID"),
    recording_date_time: str = Form(..., description="Recording timestamp (ISO 8601 or YYYY-MM-DD HH:MM:SS)"),
    db: Session = Depends(get_db),
):
    """
    Ingest a recorded CCTV video file.
    - Streams directly to disk in bounded chunks (never loads whole file into memory).
    - Enforces configured maximum file size during streaming.
    - Validates file container magic bytes (MP4, AVI, MOV).
    - Detects and rejects duplicate video slots for (batch_id, classroom_id, recording_date_time).
    - Cleans up partial or invalid files on failure.
    - Never exposes absolute server paths in responses.
    """
    batch_id = batch_id.strip()
    classroom_id = classroom_id.strip()
    if not batch_id or not classroom_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both 'batch_id' and 'classroom_id' must be non-empty."
        )

    try:
        rec_dt = parse_and_normalize_timestamp(recording_date_time)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid recording_date_time: {str(ve)}"
        )

    # Check for existing video metadata for the same slot
    existing = (
        db.query(VideoMetadata)
        .filter(
            VideoMetadata.batch_id == batch_id,
            VideoMetadata.classroom_id == classroom_id,
            VideoMetadata.recording_date_time == rec_dt,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A video for batch '{batch_id}' in classroom '{classroom_id}' at {recording_date_time} is already registered."
        )

    upload_id = str(uuid.uuid4())
    original_filename = Path(file.filename or "cctv_recording").name
    ext = Path(original_filename).suffix.lower()

    # Generate safe server-side filename using UUID
    stored_filename = f"{upload_id}{ext}"
    target_path = settings.video_upload_dir / stored_filename
    relative_path = f"{settings.UPLOAD_DIR}/videos/{stored_filename}"

    max_bytes = settings.MAX_VIDEO_SIZE_MB * 1024 * 1024

    # Stream and validate
    bytes_written, detected_ext = await stream_and_validate_video(
        file=file,
        target_path=target_path,
        max_bytes=max_bytes,
        allowed_extensions=settings.ALLOWED_VIDEO_EXTENSIONS,
    )

    try:
        # Create master upload record
        upload = Upload(
            id=upload_id,
            upload_type="video",
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_path=relative_path,
            file_size_bytes=bytes_written,
            status="VALIDATED",
            row_count=0,
            error_message=None,
        )
        db.add(upload)
        db.flush()

        video_meta = VideoMetadata(
            upload_id=upload_id,
            batch_id=batch_id,
            classroom_id=classroom_id,
            recording_date_time=rec_dt,
            file_format=detected_ext.lstrip("."),
        )
        db.add(video_meta)
        db.commit()
        db.refresh(upload)
        db.refresh(video_meta)

        return VideoUploadResponse(
            message="Video upload successfully validated and registered.",
            upload=UploadResponse.model_validate(upload),
            video_metadata=VideoMetadataResponse.model_validate(video_meta),
        )

    except IntegrityError:
        db.rollback()
        # Clean up file on disk
        target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Concurrent conflict: A video for batch '{batch_id}' in classroom '{classroom_id}' at {recording_date_time} was registered concurrently."
        )
    except Exception as exc:
        db.rollback()
        target_path.unlink(missing_ok=True)
        logger.error(f"Failed to persist video metadata: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register video metadata due to an internal server error."
        )


@router.post("/attendance", status_code=status.HTTP_201_CREATED)
async def ingest_attendance_csv(
    file: UploadFile = File(..., description="AEBAS attendance CSV file"),
    db: Session = Depends(get_db),
):
    """
    Ingest and validate mock AEBAS attendance CSV file.
    Expected schema: batch_id,person_ref,punch_in,punch_out
    - Complete pre-validation: rejects entire file on any invalid row (all-or-nothing).
    - Preserves rejection audit record in database while ensuring 0 attendance records are inserted.
    """
    original_filename = Path(file.filename or "attendance.csv").name
    upload_id = str(uuid.uuid4())

    try:
        content_bytes = await file.read()
        content_str = content_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to read uploaded file: {str(e)}"
        )

    is_valid, records, errors = validate_attendance_csv_content(content_str)

    if not is_valid:
        # Persist rejection audit record in database without any attendance records
        try:
            rejected_upload = Upload(
                id=upload_id,
                upload_type="attendance_csv",
                original_filename=original_filename,
                stored_filename=None,
                file_path=None,
                file_size_bytes=len(content_bytes),
                status="REJECTED",
                row_count=0,
                error_message="\n".join(errors),
            )
            db.add(rejected_upload)
            db.commit()
        except Exception as audit_err:
            db.rollback()
            logger.error(f"Failed to record rejection audit: {audit_err}")

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "Attendance CSV validation failed.",
                "errors": errors,
                "upload_id": upload_id,
            }
        )

    # Valid CSV: persist in single transaction
    try:
        upload = Upload(
            id=upload_id,
            upload_type="attendance_csv",
            original_filename=original_filename,
            stored_filename=None,
            file_path=None,
            file_size_bytes=len(content_bytes),
            status="VALIDATED",
            row_count=len(records),
            error_message=None,
        )
        db.add(upload)
        db.flush()

        for rec in records:
            att = AttendanceRecord(
                upload_id=upload_id,
                batch_id=rec["batch_id"],
                person_ref=rec["person_ref"],
                punch_in=rec["punch_in"],
                punch_out=rec["punch_out"],
            )
            db.add(att)

        db.commit()
        db.refresh(upload)

        return {
            "message": f"Successfully validated and imported {len(records)} attendance records.",
            "upload": UploadResponse.model_validate(upload),
            "imported_records": len(records),
        }

    except IntegrityError as ie:
        db.rollback()
        # Record duplicate error audit
        err_msg = "Database constraint violation: One or more attendance punch records already exist in the database."
        try:
            failed_upload = Upload(
                id=upload_id,
                upload_type="attendance_csv",
                original_filename=original_filename,
                file_size_bytes=len(content_bytes),
                status="REJECTED",
                row_count=0,
                error_message=err_msg,
            )
            db.add(failed_upload)
            db.commit()
        except Exception:
            db.rollback()

        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Attendance import conflict.",
                "errors": [err_msg],
                "upload_id": upload_id,
            }
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Error persisting attendance records: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist attendance records."
        )


@router.post("/schedule", status_code=status.HTTP_201_CREATED)
async def ingest_schedule_csv(
    file: UploadFile = File(..., description="Batch schedule CSV file"),
    db: Session = Depends(get_db),
):
    """
    Ingest and validate batch schedule CSV file.
    Expected schema: batch_id,classroom_id,class_date,start_time,end_time,enrolled_count
    - Enforces same-day class constraint (end_time > start_time) and non-negative enrolled count.
    - All-or-nothing validation: rejects file if any row has an error.
    - Handles cross-upload revisions deterministically (upsert).
    """
    original_filename = Path(file.filename or "schedule.csv").name
    upload_id = str(uuid.uuid4())

    try:
        content_bytes = await file.read()
        content_str = content_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to read uploaded file: {str(e)}"
        )

    is_valid, records, errors = validate_schedule_csv_content(content_str)

    if not is_valid:
        # Persist rejection audit record in database
        try:
            rejected_upload = Upload(
                id=upload_id,
                upload_type="schedule_csv",
                original_filename=original_filename,
                stored_filename=None,
                file_path=None,
                file_size_bytes=len(content_bytes),
                status="REJECTED",
                row_count=0,
                error_message="\n".join(errors),
            )
            db.add(rejected_upload)
            db.commit()
        except Exception as audit_err:
            db.rollback()
            logger.error(f"Failed to record schedule rejection audit: {audit_err}")

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "Batch schedule CSV validation failed.",
                "errors": errors,
                "upload_id": upload_id,
            }
        )

    inserted_count = 0
    updated_count = 0

    try:
        upload = Upload(
            id=upload_id,
            upload_type="schedule_csv",
            original_filename=original_filename,
            stored_filename=None,
            file_path=None,
            file_size_bytes=len(content_bytes),
            status="VALIDATED",
            row_count=len(records),
            error_message=None,
        )
        db.add(upload)
        db.flush()

        for rec in records:
            # Check for existing schedule slot to perform deterministic upsert
            existing_slot = (
                db.query(ScheduleRecord)
                .filter(
                    ScheduleRecord.batch_id == rec["batch_id"],
                    ScheduleRecord.classroom_id == rec["classroom_id"],
                    ScheduleRecord.class_date == rec["class_date"],
                    ScheduleRecord.start_time == rec["start_time"],
                )
                .first()
            )

            if existing_slot:
                # Update existing schedule revision
                existing_slot.end_time = rec["end_time"]
                existing_slot.enrolled_count = rec["enrolled_count"]
                existing_slot.upload_id = upload_id
                existing_slot.updated_at = datetime.now(timezone.utc)
                updated_count += 1
            else:
                # Insert new schedule slot
                new_slot = ScheduleRecord(
                    upload_id=upload_id,
                    batch_id=rec["batch_id"],
                    classroom_id=rec["classroom_id"],
                    class_date=rec["class_date"],
                    start_time=rec["start_time"],
                    end_time=rec["end_time"],
                    enrolled_count=rec["enrolled_count"],
                )
                db.add(new_slot)
                inserted_count += 1

        db.commit()
        db.refresh(upload)

        return {
            "message": f"Successfully processed {len(records)} schedule records ({inserted_count} inserted, {updated_count} updated).",
            "upload": UploadResponse.model_validate(upload),
            "inserted_records": inserted_count,
            "updated_records": updated_count,
        }

    except Exception as exc:
        db.rollback()
        logger.error(f"Error persisting schedule records: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist schedule records."
        )


@router.get("/uploads", response_model=UploadListResponse)
def list_uploads(
    upload_type: Optional[str] = Query(None, description="Filter by upload type (video, attendance_csv, schedule_csv)"),
    status: Optional[str] = Query(None, description="Filter by status (VALIDATED, REJECTED, FAILED)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    List previously registered uploads and their validation statuses.
    Supports filtering and pagination. Never exposes internal server paths.
    """
    query = db.query(Upload)

    if upload_type:
        query = query.filter(Upload.upload_type == upload_type.strip().lower())
    if status:
        query = query.filter(Upload.status == status.strip().upper())

    total = query.count()
    uploads = query.order_by(Upload.created_at.desc()).offset(offset).limit(limit).all()

    items = []
    for u in uploads:
        vid_meta = None
        if u.video_metadata:
            vid_meta = VideoMetadataResponse.model_validate(u.video_metadata)

        detail = UploadDetailResponse(
            id=u.id,
            upload_type=u.upload_type,
            original_filename=u.original_filename,
            file_size_bytes=u.file_size_bytes,
            status=u.status,
            row_count=u.row_count,
            error_message=u.error_message,
            created_at=u.created_at,
            video_metadata=vid_meta,
        )
        items.append(detail)

    return UploadListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/uploads/{upload_id}", response_model=UploadDetailResponse)
def get_upload_detail(
    upload_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieve metadata for an individual upload by ID.
    Never exposes internal filesystem paths.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload with ID '{upload_id}' not found."
        )

    vid_meta = None
    if upload.video_metadata:
        vid_meta = VideoMetadataResponse.model_validate(upload.video_metadata)

    return UploadDetailResponse(
        id=upload.id,
        upload_type=upload.upload_type,
        original_filename=upload.original_filename,
        file_size_bytes=upload.file_size_bytes,
        status=upload.status,
        row_count=upload.row_count,
        error_message=upload.error_message,
        created_at=upload.created_at,
        video_metadata=vid_meta,
    )


@router.get("/templates/attendance")
def get_attendance_template():
    """Returns a downloadable CSV template with sample AEBAS attendance rows."""
    template_content = (
        "batch_id,person_ref,punch_in,punch_out\n"
        "BATCH-2026-A1,CANDIDATE-101,2026-10-19 09:00:00,2026-10-19 13:00:00\n"
        "BATCH-2026-A1,CANDIDATE-102,2026-10-19 09:05:00,2026-10-19 13:02:00\n"
        "BATCH-2026-A1,CANDIDATE-103,2026-10-19 09:12:00,\n"
        "BATCH-2026-A2,CANDIDATE-201,2026-10-19 14:00:00,2026-10-19 18:00:00\n"
    )
    return Response(
        content=template_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendance_template.csv"}
    )


@router.get("/templates/schedule")
def get_schedule_template():
    """Returns a downloadable CSV template with sample batch schedule rows."""
    template_content = (
        "batch_id,classroom_id,class_date,start_time,end_time,enrolled_count\n"
        "BATCH-2026-A1,ROOM-101,2026-10-19,09:00,13:00,30\n"
        "BATCH-2026-A2,ROOM-101,2026-10-19,14:00,18:00,28\n"
        "BATCH-2026-B1,ROOM-102,2026-10-19,09:30,13:30,25\n"
    )
    return Response(
        content=template_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=schedule_template.csv"}
    )
