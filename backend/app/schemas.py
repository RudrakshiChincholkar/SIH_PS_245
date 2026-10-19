from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


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
