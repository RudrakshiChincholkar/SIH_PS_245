import csv
import io
import re
from datetime import datetime, date, time, timezone, timedelta
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from fastapi import UploadFile, HTTPException, status

# Indian Standard Time (IST) offset is UTC+05:30
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))


def parse_and_normalize_timestamp(ts_str: str) -> datetime:
    """
    Parses a timestamp string. If naive (no timezone offset specified),
    interprets it as Indian Standard Time (IST, UTC+05:30).
    Normalizes and returns a timezone-aware UTC datetime.
    
    Example:
        '2026-10-19 09:30:00' (IST) -> 2026-10-19 04:00:00+00:00 (UTC)
    """
    ts_str = ts_str.strip()
    # Try ISO formats
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        # Common fallback formats
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(ts_str, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Unable to parse timestamp: '{ts_str}'")

    if dt.tzinfo is None:
        # Naive timestamp: interpret as IST
        dt = dt.replace(tzinfo=IST_OFFSET)
    
    # Normalize to UTC
    return dt.astimezone(timezone.utc)


def parse_time_str(time_str: str) -> time:
    """Parses a time string formatted as HH:MM:SS or HH:MM."""
    time_str = time_str.strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unable to parse time: '{time_str}'. Expected HH:MM or HH:MM:SS")


def parse_date_str(date_str: str) -> date:
    """Parses a date string formatted as YYYY-MM-DD or DD-MM-YYYY."""
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unable to parse date: '{date_str}'. Expected YYYY-MM-DD")


def validate_video_magic_bytes(header: bytes, ext: str) -> bool:
    """
    Validates the container format of a video file by inspecting magic bytes.
    Does not decode video frames (strictly Part 2 scope).
    """
    ext = ext.lower()
    if len(header) < 12:
        return False

    if ext == ".mp4":
        # MP4 files have 'ftyp' at bytes 4..8
        return header[4:8] == b"ftyp"
    elif ext == ".avi":
        # AVI files start with 'RIFF' and have 'AVI ' at bytes 8..12
        return header[0:4] == b"RIFF" and header[8:12] == b"AVI "
    elif ext == ".mov":
        # QuickTime MOV files have 'ftypqt  ' or atom headers like moov, mdat, wide, free
        if header[4:8] == b"ftyp":
            return True
        atom_type = header[4:8]
        return atom_type in (b"moov", b"mdat", b"wide", b"free")
    return False


async def stream_and_validate_video(
    file: UploadFile,
    target_path: Path,
    max_bytes: int,
    allowed_extensions: List[str]
) -> Tuple[int, str]:
    """
    Streams a video upload chunk-by-chunk directly to disk.
    Never loads the entire video file into memory.
    
    - Validates extension against allowed_extensions.
    - Inspects initial chunk for container magic bytes.
    - Enforces max_bytes limit during streaming.
    - If validation fails, cleans up the partial file and raises HTTPException.
    
    Returns:
        (total_bytes_written, file_extension)
    """
    original_filename = file.filename or "uploaded_video"
    ext = Path(original_filename).suffix.lower()

    if ext not in [e.lower() for e in allowed_extensions]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{ext}'. Allowed extensions: {', '.join(allowed_extensions)}"
        )

    bytes_written = 0
    first_chunk = True
    chunk_size = 1024 * 1024  # 1 MB chunk

    try:
        with open(target_path, "wb") as f_out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break

                if first_chunk:
                    # Validate magic bytes on initial segment
                    if not validate_video_magic_bytes(chunk, ext):
                        raise HTTPException(
                            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail=f"Invalid media format: file header does not match a valid {ext.upper()} container."
                        )
                    first_chunk = False

                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    max_mb = max_bytes // (1024 * 1024)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Video file exceeds maximum permitted upload limit of {max_mb} MB."
                    )

                f_out.write(chunk)

        if bytes_written == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded video file is empty."
            )

        return bytes_written, ext

    except Exception:
        # Guarantee partial or invalid file cleanup on any failure
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise


def validate_attendance_csv_content(content: str) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    """
    Validates complete attendance CSV content before database insertion.
    Schema: batch_id,person_ref,punch_in,punch_out
    
    Returns:
        (is_valid, records, error_list)
    """
    errors: List[str] = []
    records: List[Dict[str, Any]] = []

    # Strip BOM and whitespace
    clean_content = content.lstrip("\ufeff").strip()
    if not clean_content:
        return False, [], ["CSV file is empty."]

    reader = csv.reader(io.StringIO(clean_content))
    try:
        headers = [h.strip().lower() for h in next(reader, [])]
    except Exception as e:
        return False, [], [f"Failed to read CSV header: {str(e)}"]

    expected_headers = ["batch_id", "person_ref", "punch_in", "punch_out"]
    if headers != expected_headers:
        return False, [], [
            f"Invalid CSV headers: got {headers}. Expected exact order: {expected_headers}"
        ]

    seen_punches = set()

    for row_idx, row in enumerate(reader, start=2):
        if not row or all(c.strip() == "" for c in row):
            continue  # skip blank lines

        if len(row) < 4:
            errors.append(f"Row {row_idx}: Missing columns. Expected 4 columns, got {len(row)}.")
            continue

        batch_id = row[0].strip()
        person_ref = row[1].strip()
        punch_in_raw = row[2].strip()
        punch_out_raw = row[3].strip()

        if not batch_id:
            errors.append(f"Row {row_idx}: 'batch_id' cannot be blank.")
        if not person_ref:
            errors.append(f"Row {row_idx}: 'person_ref' cannot be blank.")
        if not punch_in_raw:
            errors.append(f"Row {row_idx}: 'punch_in' timestamp cannot be blank.")
            continue

        # Validate punch_in timestamp
        try:
            punch_in_dt = parse_and_normalize_timestamp(punch_in_raw)
        except ValueError as ve:
            errors.append(f"Row {row_idx}: Invalid punch_in timestamp '{punch_in_raw}' ({ve}).")
            punch_in_dt = None

        # Validate punch_out timestamp (optional)
        punch_out_dt = None
        if punch_out_raw:
            try:
                punch_out_dt = parse_and_normalize_timestamp(punch_out_raw)
            except ValueError as ve:
                errors.append(f"Row {row_idx}: Invalid punch_out timestamp '{punch_out_raw}' ({ve}).")

        # Validate punch interval: punch_out cannot be earlier than punch_in
        if punch_in_dt and punch_out_dt:
            if punch_out_dt < punch_in_dt:
                errors.append(
                    f"Row {row_idx}: punch_out ({punch_out_raw}) cannot be earlier than punch_in ({punch_in_raw})."
                )

        # Detect intra-file duplicate punches
        if batch_id and person_ref and punch_in_dt:
            punch_key = (batch_id, person_ref, punch_in_dt)
            if punch_key in seen_punches:
                errors.append(
                    f"Row {row_idx}: Duplicate punch detected for person_ref '{person_ref}' in batch '{batch_id}' at {punch_in_raw}."
                )
            else:
                seen_punches.add(punch_key)

        if not errors or len(errors) == 0:
            records.append({
                "batch_id": batch_id,
                "person_ref": person_ref,
                "punch_in": punch_in_dt,
                "punch_out": punch_out_dt,
            })

    if len(seen_punches) == 0 and len(errors) == 0:
        errors.append("CSV file contains no valid data rows.")

    is_valid = len(errors) == 0
    return is_valid, records if is_valid else [], errors


def validate_schedule_csv_content(content: str) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    """
    Validates complete batch schedule CSV content before database insertion.
    Schema: batch_id,classroom_id,class_date,start_time,end_time,enrolled_count
    
    Enforces:
    - Same-calendar-day class constraint: end_time > start_time
    - Enrolled count >= 0
    - Detection of conflicting duplicate slots in a single file
    
    Returns:
        (is_valid, records, error_list)
    """
    errors: List[str] = []
    records: List[Dict[str, Any]] = []

    clean_content = content.lstrip("\ufeff").strip()
    if not clean_content:
        return False, [], ["CSV file is empty."]

    reader = csv.reader(io.StringIO(clean_content))
    try:
        headers = [h.strip().lower() for h in next(reader, [])]
    except Exception as e:
        return False, [], [f"Failed to read CSV header: {str(e)}"]

    expected_headers = ["batch_id", "classroom_id", "class_date", "start_time", "end_time", "enrolled_count"]
    if headers != expected_headers:
        return False, [], [
            f"Invalid CSV headers: got {headers}. Expected exact order: {expected_headers}"
        ]

    seen_slots: Dict[Tuple[str, str, date, time], Dict[str, Any]] = {}

    for row_idx, row in enumerate(reader, start=2):
        if not row or all(c.strip() == "" for c in row):
            continue

        if len(row) < 6:
            errors.append(f"Row {row_idx}: Missing columns. Expected 6 columns, got {len(row)}.")
            continue

        batch_id = row[0].strip()
        classroom_id = row[1].strip()
        class_date_raw = row[2].strip()
        start_time_raw = row[3].strip()
        end_time_raw = row[4].strip()
        enrolled_count_raw = row[5].strip()

        if not batch_id:
            errors.append(f"Row {row_idx}: 'batch_id' cannot be blank.")
        if not classroom_id:
            errors.append(f"Row {row_idx}: 'classroom_id' cannot be blank.")

        # Parse date
        try:
            class_date_val = parse_date_str(class_date_raw)
        except ValueError as ve:
            errors.append(f"Row {row_idx}: Invalid class_date '{class_date_raw}' ({ve}).")
            class_date_val = None

        # Parse start_time
        try:
            start_time_val = parse_time_str(start_time_raw)
        except ValueError as ve:
            errors.append(f"Row {row_idx}: Invalid start_time '{start_time_raw}' ({ve}).")
            start_time_val = None

        # Parse end_time
        try:
            end_time_val = parse_time_str(end_time_raw)
        except ValueError as ve:
            errors.append(f"Row {row_idx}: Invalid end_time '{end_time_raw}' ({ve}).")
            end_time_val = None

        # Enforce same-day class constraint: end_time must be after start_time
        if start_time_val and end_time_val:
            if end_time_val <= start_time_val:
                errors.append(
                    f"Row {row_idx}: end_time ({end_time_raw}) must be strictly after start_time ({start_time_raw})."
                )

        # Parse enrolled count
        try:
            enrolled_count_val = int(enrolled_count_raw)
            if enrolled_count_val < 0:
                errors.append(f"Row {row_idx}: enrolled_count must be a non-negative integer (got {enrolled_count_val}).")
        except ValueError:
            errors.append(f"Row {row_idx}: enrolled_count must be an integer (got '{enrolled_count_raw}').")
            enrolled_count_val = None

        # Check for intra-file duplicates
        if batch_id and classroom_id and class_date_val and start_time_val:
            slot_key = (batch_id, classroom_id, class_date_val, start_time_val)
            if slot_key in seen_slots:
                prev = seen_slots[slot_key]
                if prev["end_time"] != end_time_val or prev["enrolled_count"] != enrolled_count_val:
                    errors.append(
                        f"Row {row_idx}: Conflicting duplicate schedule entry for batch '{batch_id}', classroom '{classroom_id}' on {class_date_raw} at {start_time_raw}."
                    )
                else:
                    errors.append(
                        f"Row {row_idx}: Redundant duplicate schedule entry for batch '{batch_id}', classroom '{classroom_id}' on {class_date_raw} at {start_time_raw}."
                    )
            else:
                seen_slots[slot_key] = {
                    "row_idx": row_idx,
                    "end_time": end_time_val,
                    "enrolled_count": enrolled_count_val
                }

        if not errors or len(errors) == 0:
            records.append({
                "batch_id": batch_id,
                "classroom_id": classroom_id,
                "class_date": class_date_val,
                "start_time": start_time_val,
                "end_time": end_time_val,
                "enrolled_count": enrolled_count_val,
            })

    if len(seen_slots) == 0 and len(errors) == 0:
        errors.append("CSV file contains no valid data rows.")

    is_valid = len(errors) == 0
    return is_valid, records if is_valid else [], errors
