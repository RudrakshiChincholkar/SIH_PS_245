"""Compare YOLOv8n vs YOLOv8s on the same test video frames."""

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


def run_experiment(model_name, model_path, video_path, sample_times, fps, confidence=0.25, iou=0.45):
    """Run detection experiment with a specific model."""
    print(f"\n{'='*60}")
    print(f"Testing {model_name}")
    print(f"{'='*60}")

    # Initialize detector
    print(f"Loading {model_name} model...")
    detector = YOLOPersonDetector(
        model_path=model_path,
        confidence_threshold=confidence,
        iou_threshold=iou,
        device="cpu",
    )
    print("Model loaded.")

    # Open video
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print("Failed to open video")
        return None

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

        # Run detection with timing (skip first frame for warm-up)
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

    # Summary statistics (exclude first frame for steady-state metrics)
    steady_state_results = results[1:] if len(results) > 1 else results
    avg_latency = np.mean([r['inference_ms'] for r in steady_state_results if 'inference_ms' in r])
    peak_memory = max([r['memory_mb'] for r in results if 'memory_mb' in r])

    print(f"\n{model_name} Summary:")
    print(f"  Total frames: {len(results)}")
    print(f"  Total detections: {sum(r['count'] for r in results)}")
    print(f"  Avg inference (steady-state): {avg_latency:.2f}ms/frame")
    print(f"  Peak memory: {peak_memory:.2f}MB")

    return results


def compare_with_manual(results, model_name, manual_counts):
    """Compare predictions with manual ground truth."""
    print(f"\n{model_name} vs Manual Ground Truth:")
    print(f"{'Time':>6s} {'Manual':>6s} {'Pred':>6s} {'Error':>6s}")
    print("-" * 30)

    abs_errors = []
    false_zeros = 0
    for r in results:
        manual = manual_counts.get(r["timestamp"])
        predicted = r["count"]
        error = abs(predicted - manual) if manual is not None else None
        if error is not None:
            abs_errors.append(error)
        if manual is not None and manual > 0 and predicted == 0:
            false_zeros += 1
        print(f"{r['timestamp']:6.1f} {manual if manual is not None else 'N/A':>6} {predicted if predicted is not None else 'N/A':>6} {error if error is not None else 'N/A':>6}")

    if abs_errors:
        mae = np.mean(abs_errors)
        exact_agreement = sum(1 for r in results if manual_counts.get(r["timestamp"]) == r["count"])
        print(f"\nCount MAE: {mae:.3f}")
        print(f"Exact count agreement: {exact_agreement}/{len(results)}")
        print(f"False-zero frames: {false_zeros}")

    return {
        "mae": np.mean(abs_errors) if abs_errors else None,
        "exact_agreement": sum(1 for r in results if manual_counts.get(r["timestamp"]) == r["count"]),
        "false_zeros": false_zeros,
    }


def main():
    video_path = Path(settings.video_upload_dir) / "469a642f-8699-41d9-ac19-bc485eb3e86e.mp4"
    if not video_path.is_file():
        print(f"Video not found: {video_path}")
        return

    # Production configuration
    confidence = 0.25
    iou = 0.45
    sample_interval = 10.0
    sample_times = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0]

    # Get video metadata
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    print(f"Video: {video_path}")
    print(f"Configuration: conf={confidence}, iou={iou}")
    print(f"Sample interval: {sample_interval}s, {len(sample_times)} frames")

    # Manual ground truth from evaluation document
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

    # Test YOLOv8n (baseline)
    results_n = run_experiment(
        "YOLOv8n",
        "yolov8n.pt",
        video_path,
        sample_times,
        fps,
        confidence,
        iou,
    )

    metrics_n = compare_with_manual(results_n, "YOLOv8n", manual_counts)

    # Check if YOLOv8s weights exist, download if needed
    yolov8s_path = Path(backend_root) / "yolov8s.pt"
    if not yolov8s_path.is_file():
        from ultralytics.utils import WEIGHTS_DIR
        yolov8s_path = Path(WEIGHTS_DIR) / "yolov8s.pt"

    if not yolov8s_path.is_file():
        print(f"\nYOLOv8s weights not found")
        print("Estimating download size: ~22MB")
        response = input("Download YOLOv8s weights? (y/n): ")
        if response.lower() == 'y':
            print("Downloading YOLOv8s.pt...")
            from ultralytics import YOLO
            model = YOLO("yolov8s.pt")
            print("Download complete.")
            # Find where Ultralytics saved it
            from ultralytics.utils import WEIGHTS_DIR
            downloaded_path = Path(WEIGHTS_DIR) / "yolov8s.pt"
            if downloaded_path.is_file():
                yolov8s_path = downloaded_path
                print(f"Weights saved to: {yolov8s_path}")
            else:
                print("Could not locate downloaded weights")
                return
        else:
            print("Skipping YOLOv8s comparison")
            return

    # Test YOLOv8s
    results_s = run_experiment(
        "YOLOv8s",
        str(yolov8s_path),
        video_path,
        sample_times,
        fps,
        confidence,
        iou,
    )

    metrics_s = compare_with_manual(results_s, "YOLOv8s", manual_counts)

    # Final comparison table
    print("\n" + "="*60)
    print("FINAL COMPARISON: YOLOv8n vs YOLOv8s")
    print("="*60)
    print(f"{'Metric':<30} {'YOLOv8n':>12} {'YOLOv8s':>12}")
    print("-" * 60)
    print(f"{'Count MAE':<30} {metrics_n['mae']:>12.3f} {metrics_s['mae']:>12.3f}")
    print(f"{'Exact count agreement':<30} {metrics_n['exact_agreement']:>12}/{len(sample_times)} {metrics_s['exact_agreement']:>12}/{len(sample_times)}")
    print(f"{'False-zero frames':<30} {metrics_n['false_zeros']:>12} {metrics_s['false_zeros']:>12}")

    # Resource comparison
    steady_n = results_n[1:]
    steady_s = results_s[1:]
    avg_latency_n = np.mean([r['inference_ms'] for r in steady_n])
    avg_latency_s = np.mean([r['inference_ms'] for r in steady_s])
    peak_mem_n = max([r['memory_mb'] for r in results_n])
    peak_mem_s = max([r['memory_mb'] for r in results_s])

    print(f"{'Avg inference (steady-state)':<30} {avg_latency_n:>12.2f}ms {avg_latency_s:>12.2f}ms")
    print(f"{'Peak memory':<30} {peak_mem_n:>12.2f}MB {peak_mem_s:>12.2f}MB")
    print(f"{'Latency increase':<30} {'N/A':>12} {avg_latency_s/avg_latency_n:>12.2f}x")
    print(f"{'Memory increase':<30} {'N/A':>12} {peak_mem_s/peak_mem_n:>12.2f}x")


if __name__ == "__main__":
    main()
