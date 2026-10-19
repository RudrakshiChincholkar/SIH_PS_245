from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Text,
    DateTime,
    Date,
    Time,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utc_now():
    return datetime.now(timezone.utc)


class Upload(Base):
    """
    Master registry for all file uploads (videos, attendance CSVs, schedule CSVs).
    Tracks validation statuses, row counts, and rejection errors.
    """
    __tablename__ = "uploads"

    id = Column(String(36), primary_key=True, index=True)
    upload_type = Column(String(30), nullable=False, index=True)  # 'video', 'attendance_csv', 'schedule_csv'
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=True)
    file_path = Column(String(512), nullable=True)  # Relative safe path, never absolute
    file_size_bytes = Column(BigInteger, nullable=False, default=0)
    status = Column(String(30), nullable=False, default="PENDING", index=True)  # 'VALIDATED', 'REJECTED', 'FAILED'
    row_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    video_metadata = relationship("VideoMetadata", back_populates="upload", uselist=False, cascade="all, delete-orphan")
    attendance_records = relationship("AttendanceRecord", back_populates="upload", cascade="all, delete-orphan")
    schedule_records = relationship("ScheduleRecord", back_populates="upload", cascade="all, delete-orphan")


class VideoMetadata(Base):
    """
    Metadata associated with an ingested CCTV video file.
    """
    __tablename__ = "video_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_id = Column(String(36), ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    batch_id = Column(String(100), nullable=False, index=True)
    classroom_id = Column(String(100), nullable=False, index=True)
    recording_date_time = Column(DateTime(timezone=True), nullable=False, index=True)
    file_format = Column(String(10), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    upload = relationship("Upload", back_populates="video_metadata")

    __table_args__ = (
        UniqueConstraint("batch_id", "classroom_id", "recording_date_time", name="uq_video_slot"),
    )


class AttendanceRecord(Base):
    """
    Validated attendance punches ingested from mock AEBAS records.
    """
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_id = Column(String(36), ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id = Column(String(100), nullable=False, index=True)
    person_ref = Column(String(100), nullable=False, index=True)
    punch_in = Column(DateTime(timezone=True), nullable=False, index=True)
    punch_out = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    upload = relationship("Upload", back_populates="attendance_records")

    __table_args__ = (
        UniqueConstraint("batch_id", "person_ref", "punch_in", name="uq_attendance_punch"),
    )


class ScheduleRecord(Base):
    """
    Validated training centre timetable schedule slots.
    """
    __tablename__ = "schedule_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_id = Column(String(36), ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id = Column(String(100), nullable=False, index=True)
    classroom_id = Column(String(100), nullable=False, index=True)
    class_date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    enrolled_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    upload = relationship("Upload", back_populates="schedule_records")

    __table_args__ = (
        UniqueConstraint("batch_id", "classroom_id", "class_date", "start_time", name="uq_schedule_slot"),
    )
