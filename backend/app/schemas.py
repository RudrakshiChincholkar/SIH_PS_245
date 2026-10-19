from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class VideoMetadataResponse(BaseModel):
    batch_id: str
    classroom_id: str
    recording_date_time: datetime
    file_format: str

    model_config = ConfigDict(from_attributes=True)


class UploadResponse(BaseModel):
    id: str
    upload_type: str
    original_filename: str
    file_size_bytes: int
    status: str
    row_count: int
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UploadDetailResponse(UploadResponse):
    video_metadata: Optional[VideoMetadataResponse] = None


class UploadListResponse(BaseModel):
    items: List[UploadDetailResponse]
    total: int
    limit: int
    offset: int


class VideoUploadResponse(BaseModel):
    message: str
    upload: UploadResponse
    video_metadata: VideoMetadataResponse


class AttendanceUploadResponse(BaseModel):
    message: str
    upload: UploadResponse
    imported_records: int


class ScheduleUploadResponse(BaseModel):
    message: str
    upload: UploadResponse
    inserted_records: int
    updated_records: int


class ValidationErrorResponse(BaseModel):
    detail: str
    errors: List[str]
    upload_id: Optional[str] = None


QUALITY_SAFETY_NOTE = (
    "Quality assessment measures footage legibility only. "
    "It does not count people or infer zero occupancy."
)


class VideoQualityAssessmentResponse(BaseModel):
    upload_id: str
    processing_status: str
    overall_quality: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    reported_frame_count: Optional[int] = None
    duration_seconds: Optional[float] = None
    sample_interval_seconds: float
    samples_attempted: int
    samples_successful: int
    samples_failed: int
    decode_success_ratio: Optional[float] = None
    avg_blur_score: Optional[float] = None
    avg_luminance: Optional[float] = None
    avg_temporal_difference: Optional[float] = None
    quality_flags: List[str] = Field(default_factory=list)
    diagnostic_message: Optional[str] = None
    analysis_count: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    safety_note: str = QUALITY_SAFETY_NOTE

    model_config = ConfigDict(from_attributes=True)


class VideoProcessResponse(BaseModel):
    message: str
    assessment: VideoQualityAssessmentResponse
