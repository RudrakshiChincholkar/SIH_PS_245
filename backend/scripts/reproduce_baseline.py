"""Reproduce baseline YOLOv8n detection on the documented test video frames."""

import sys
import time
import tracemalloc
from pathlib import Path

import cv2
import numpy as np

backend_root = str(Path(__file__).resolve().parents[1])
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.person_detector import YOLOPersonDetector
from app.config import settings


def main():
    video_path = Path(settings.video_upload_dir) / "469a642f-8699-41d9-ac19-bc485eb3e86e.mp4"
    if not video_path.is_file():
        print(f"Video not found: {video_path}")
        return

    # Production configuration
    upload_id = "469a642f-8699-41d9-ac19-bc485eb3e86e"
    sample_interval = 10.0  # seconds
    confidence = 0.25
    iou = 0.45
    imgsz = 640

    print(f"Video: {video_path}")
    print(f"Configuration: conf={confidence}, iou={iou}, imgsz={imgsz}")
    print(f"Sample interval: {sample_interval}s")
    print()

    # Initialize detector
    print("Loading YOLOv8n model...")
    detector = YOLOPersonDetector(
        model_path="yolov8n.pt",
        confidence_threshold=confidence,
        iou_threshold=iou,
        device="cpu",
    )
    print("Model loaded.")
    print()

    # Open video
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print("Failed to open video")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Video metadata: {width}x{height}, {fps} FPS, {frame_count} frames")
    print()

    # Sample frames at the documented timestamps
    sample_times = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0]
    results = []

    for sample_t in sample_times:
        frame_index = int(sample_t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        success, frame = cap.read()

        if not success:
            print(f"Failed to read frame at {sample_t}s (index {frame_index})")
            results.append({
                "timestamp": sample_t,
                "frame_index": frame_index,
                "status": "DECODE_FAILED",
                "count": None,
                "detections": [],
            })
            continue

        # Run detection with timing
        tracemalloc.start()
        start_time = time.perf_counter()

        detections = detector.detect(frame)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        results.append({
            "timestamp": sample_t,
            "frame_index": frame_index,
            "status": "SUCCESS",
            "count": len(detections),
            "detections": [
                {
                    "box": det.box,
                    "confidence": det.confidence,
                }
                for det in detections
            ],
            "inference_ms": elapsed_ms,
            "memory_mb": peak / 1024 / 1024,
        })

        print(f"t={sample_t:5.1f}s (frame {frame_index:4d}): {len(detections)} detections, {elapsed_ms:.1f}ms, {peak/1024/1024:.1f}MB peak")
        if detections:
            for det in detections:
                print(f"  - box={det.box}, conf={det.confidence:.4f}")

    cap.release()

    # Summary
    print()
    print("=" * 60)
    print("BASELINE REPRODUCTION SUMMARY")
    print("=" * 60)
    print(f"Total frames sampled: {len(results)}")
    print(f"Successful detections: {sum(1 for r in results if r['status'] == 'SUCCESS')}")
    print(f"Total people detected: {sum(r['count'] for r in results)}")
    print(f"Average inference time: {np.mean([r['inference_ms'] for r in results if 'inference_ms' in r]):.2f}ms/frame")
    print(f"Peak memory: {max(r['memory_mb'] for r in results if 'memory_mb' in r):.2f}MB")
    print()

    # Compare with documented manual counts
    manual_counts = {
        0.0: 2,
        10.0: 1,
        20.0: 2,
        30.0: 1,
        40.0: 0,
        50.0: 0,
        60.0: 0,
        70.0: 0,
        80.0: 0,
        90.0: 0,
        100.0: 0,
        110.0: 2,
    }

    print("Comparison with manual ground truth:")
    print(f"{'Time':>6s} {'Manual':>6s} {'YOLOv8n':>8s} {'Error':>6s}")
    print("-" * 30)
    abs_errors = []
    for r in results:
        manual = manual_counts.get(r["timestamp"])
        predicted = r["count"]
        error = abs(predicted - manual) if manual is not None else None
        if error is not None:
            abs_errors.append(error)
        print(f"{r['timestamp']:6.1f} {manual if manual is not None else 'N/A':>6} {predicted if predicted is not None else 'N/A':>8} {error if error is not None else 'N/A':>6}")

    print()
    if abs_errors:
        mae = np.mean(abs_errors)
        exact_agreement = sum(1 for r in results if manual_counts.get(r["timestamp"]) == r["count"])
        print(f"Count MAE: {mae:.3f}")
        print(f"Exact count agreement: {exact_agreement}/{len(results)}")
        print(f"False-zero frames (manual>0, pred=0): {sum(1 for r in results if manual_counts.get(r['timestamp'], 0) > 0 and r['count'] == 0)}")


if __name__ == "__main__":
    main()
