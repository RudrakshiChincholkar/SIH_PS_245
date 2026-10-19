"""CPU-only YOLO person detector; no identity or tracking logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

import cv2
import numpy as np

from app.config import settings


class DetectorUnavailableError(RuntimeError):
    """The YOLO package or pretrained weights could not be loaded."""


@dataclass(frozen=True)
class PersonDetection:
    box: Sequence[float]
    confidence: float


def filter_and_suppress_detections(
    detections: Sequence[PersonDetection],
    confidence_threshold: float,
    iou_threshold: float,
) -> List[PersonDetection]:
    """Apply confidence filtering and OpenCV's supported box NMS."""
    candidates = [
        detection
        for detection in detections
        if np.isfinite(detection.confidence)
        and detection.confidence >= confidence_threshold
        and len(detection.box) == 4
        and all(np.isfinite(value) for value in detection.box)
        and detection.box[2] > detection.box[0]
        and detection.box[3] > detection.box[1]
    ]
    if not candidates:
        return []

    boxes = []
    for detection in candidates:
        x1, y1, x2, y2 = (float(value) for value in detection.box)
        boxes.append([x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)])

    kept = cv2.dnn.NMSBoxes(
        boxes,
        [float(detection.confidence) for detection in candidates],
        float(confidence_threshold),
        float(iou_threshold),
    )
    if kept is None or len(kept) == 0:
        return []
    indices = np.asarray(kept).reshape(-1).tolist()
    return [candidates[int(index)] for index in indices]


class YOLOPersonDetector:
    """Ultralytics YOLOv8n COCO detector forced to CPU and person class only."""

    PERSON_CLASS_ID = 0

    def __init__(
        self,
        model_path: str = settings.PERSON_DETECTOR_MODEL,
        confidence_threshold: float = settings.PERSON_DETECTION_CONFIDENCE,
        iou_threshold: float = settings.PERSON_DETECTION_IOU,
        device: str = settings.PERSON_DETECTION_DEVICE,
    ) -> None:
        if device.lower() != "cpu":
            raise ValueError("Person detection is configured for CPU-only inference.")
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        try:
            from ultralytics import YOLO

            self.model = YOLO(model_path)
        except Exception as exc:
            raise DetectorUnavailableError(
                "Could not load YOLO weights. Check the configured model path and "
                "download access for the initial weights setup."
            ) from exc

    def detect(self, frame: np.ndarray) -> List[PersonDetection]:
        try:
            results = self.model.predict(
                source=frame,
                device="cpu",
                classes=[self.PERSON_CLASS_ID],
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                verbose=False,
            )
            raw: List[PersonDetection] = []
            for result in results:
                if result.boxes is None:
                    continue
                boxes = result.boxes
                coordinates = boxes.xyxy.cpu().numpy()
                confidences = boxes.conf.cpu().numpy()
                classes = boxes.cls.cpu().numpy().astype(int)
                for box, confidence, class_id in zip(coordinates, confidences, classes):
                    if class_id == self.PERSON_CLASS_ID:
                        raw.append(PersonDetection(box.tolist(), float(confidence)))
            return filter_and_suppress_detections(
                raw,
                self.confidence_threshold,
                self.iou_threshold,
            )
        except Exception as exc:
            raise RuntimeError("YOLO inference failed for a sampled frame.") from exc
