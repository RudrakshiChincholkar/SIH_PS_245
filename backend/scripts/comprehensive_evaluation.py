"""Comprehensive evaluation of YOLOv8n vs YOLOv8s with proper metrics."""

import sys
import json
from pathlib import Path

backend_root = str(Path(__file__).resolve().parents[1])
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from scripts.evaluate_detector import evaluate_count_level


def load_comparison_results(results_file: Path) -> dict:
    """Load comparison results from JSON file."""
    if results_file.exists():
        with open(results_file) as f:
            return json.load(f)
    return None


def main():
    # Ground truth from documentation
    ground_truth_counts = {
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

    # Results from compare_models.py (manually transcribed for this evaluation)
    # In a real workflow, these would be loaded from a JSON file
    yolo8n_results = [
        {"timestamp": 0.0, "count": 0},
        {"timestamp": 10.0, "count": 1},
        {"timestamp": 20.0, "count": 0},
        {"timestamp": 30.0, "count": 0},
        {"timestamp": 40.0, "count": 0},
        {"timestamp": 50.0, "count": 0},
        {"timestamp": 60.0, "count": 0},
        {"timestamp": 70.0, "count": 0},
        {"timestamp": 80.0, "count": 0},
        {"timestamp": 90.0, "count": 0},
        {"timestamp": 100.0, "count": 0},
        {"timestamp": 110.0, "count": 0},
    ]

    yolo8s_results = [
        {"timestamp": 0.0, "count": 0},
        {"timestamp": 10.0, "count": 1},
        {"timestamp": 20.0, "count": 1},
        {"timestamp": 30.0, "count": 0},
        {"timestamp": 40.0, "count": 0},
        {"timestamp": 50.0, "count": 0},
        {"timestamp": 60.0, "count": 0},
        {"timestamp": 70.0, "count": 0},
        {"timestamp": 80.0, "count": 0},
        {"timestamp": 90.0, "count": 0},
        {"timestamp": 100.0, "count": 0},
        {"timestamp": 110.0, "count": 1},
    ]

    # Evaluate both models
    n_metrics = evaluate_count_level(yolo8n_results, ground_truth_counts)
    s_metrics = evaluate_count_level(yolo8s_results, ground_truth_counts)

    print("=" * 80)
    print("COMPREHENSIVE EVALUATION: YOLOv8n vs YOLOv8s")
    print("=" * 80)
    print()
    print("Ground Truth Summary:")
    print(f"  Total frames: {len(ground_truth_counts)}")
    print(f"  Occupied frames (count > 0): {sum(1 for c in ground_truth_counts.values() if c > 0)}")
    print(f"  Empty frames (count = 0): {sum(1 for c in ground_truth_counts.values() if c == 0)}")
    print(f"  Total visible people: {sum(ground_truth_counts.values())}")
    print()

    print("-" * 80)
    print("COUNT-LEVEL METRICS")
    print("-" * 80)
    print()
    print(f"{'Metric':<30} {'YOLOv8n':>15} {'YOLOv8s':>15} {'Improvement':>15}")
    print("-" * 80)
    print(f"{'Mean Absolute Error (MAE)':<30} {n_metrics['mae']:>15.3f} {s_metrics['mae']:>15.3f} {(n_metrics['mae'] - s_metrics['mae']):>15.3f}")
    print(f"{'Median Absolute Error':<30} {n_metrics['median_ae']:>15.3f} {s_metrics['median_ae']:>15.3f} {(n_metrics['median_ae'] - s_metrics['median_ae']):>15.3f}")
    print(f"{'Exact Count Agreement':<30} {n_metrics['exact_agreement']:>15}/{n_metrics['total_frames']} {s_metrics['exact_agreement']:>15}/{s_metrics['total_frames']} {s_metrics['exact_agreement'] - n_metrics['exact_agreement']:>15}")
    print(f"{'False-Zero Frames':<30} {n_metrics['false_zeros']:>15} {s_metrics['false_zeros']:>15} {n_metrics['false_zeros'] - s_metrics['false_zeros']:>15}")
    print(f"{'False-Positive Frames':<30} {n_metrics['false_positives']:>15} {s_metrics['false_positives']:>15} {n_metrics['false_positives'] - s_metrics['false_positives']:>15}")
    print()

    # Resource usage from compare_models.py
    print("-" * 80)
    print("RESOURCE USAGE (steady-state, excluding first frame)")
    print("-" * 80)
    print()
    print(f"{'Metric':<30} {'YOLOv8n':>15} {'YOLOv8s':>15} {'Ratio (s/n)':>15}")
    print("-" * 80)
    print(f"{'Avg Inference Latency':<30} {60.72:>15.2f}ms {98.37:>15.2f}ms {98.37/60.72:>15.2f}x")
    print(f"{'Peak Memory':<30} {64.85:>15.2f}MB {1.63:>15.2f}MB {1.63/64.85:>15.2f}x")
    print()

    # Detailed frame-by-frame comparison
    print("-" * 80)
    print("FRAME-BY-FRAME COMPARISON")
    print("-" * 80)
    print()
    print(f"{'Time':>6s} {'GT':>4s} {'v8n':>4s} {'v8s':>4s} {'n_err':>6s} {'s_err':>6s} {'Better':>6s}")
    print("-" * 45)
    for i, (t, gt) in enumerate(sorted(ground_truth_counts.items())):
        n_pred = yolo8n_results[i]["count"]
        s_pred = yolo8s_results[i]["count"]
        n_err = abs(n_pred - gt)
        s_err = abs(s_pred - gt)
        better = "v8s" if s_err < n_err else ("v8n" if n_err < s_err else "tie")
        print(f"{t:6.1f} {gt:4d} {n_pred:4d} {s_pred:4d} {n_err:6d} {s_err:6d} {better:>6s}")
    print()

    # Analysis
    print("=" * 80)
    print("ANALYSIS")
    print("=" * 80)
    print()
    print("YOLOv8s Improvements:")
    print(f"  - Count MAE reduced by {(n_metrics['mae'] - s_metrics['mae']):.3f} ({(n_metrics['mae'] - s_metrics['mae'])/n_metrics['mae']*100:.1f}% relative)")
    print(f"  - False-zero frames reduced from {n_metrics['false_zeros']} to {s_metrics['false_zeros']}")
    print(f"  - Recovered 1 person at 20s (1 of 2 visible)")
    print(f"  - Recovered 1 person at 110s (1 of 2 visible)")
    print()
    print("YOLOv8s Limitations:")
    print(f"  - Still misses 1 person at 0s (2 visible, 0 detected)")
    print(f"  - Still misses 1 person at 20s (2 visible, 1 detected)")
    print(f"  - Still misses 1 person at 30s (1 visible, 0 detected)")
    print(f"  - Still misses 1 person at 110s (2 visible, 1 detected)")
    print(f"  - Exact count agreement unchanged at 8/12")
    print()
    print("Resource Cost:")
    print(f"  - Inference latency increased by {98.37/60.72:.2f}x (from ~61ms to ~98ms per frame)")
    print(f"  - For a 2-hour video at 10s sampling: ~720 frames, ~44s vs ~71s total inference time")
    print(f"  - Memory usage is negligible in both cases")
    print()
    print("Key Observations:")
    print("  1. YOLOv8s shows modest count-level improvement (MAE 0.583 -> 0.417)")
    print("  2. False-zero rate reduced from 4/12 to 2/12 frames")
    print("  3. However, 5 of 8 visible people are still missed by YOLOv8s")
    print("  4. Exact count agreement did not improve (remains 8/12)")
    print("  5. Latency increase is significant for CPU-only deployment")
    print("  6. The improvement does not justify the 1.62x latency cost for this workload")
    print()

    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print()
    print("Keep YOLOv8n as the baseline model.")
    print()
    print("Rationale:")
    print("  - The accuracy improvement from YOLOv8s is marginal and not operationally significant")
    print("  - 5 of 8 visible people are still missed by YOLOv8s; the model limitation persists")
    print("  - Exact count agreement is unchanged (8/12 frames)")
    print("  - The 1.62x latency increase is non-trivial for CPU-only deployment")
    print("  - Neither model meets a reasonable reliability threshold for occupancy decisions")
    print()
    print("Recommended Next Steps:")
    print("  1. Expand the evaluation set with more diverse videos and camera angles")
    print("  2. Annotate bounding boxes to compute person-level precision/recall/F1")
    print("  3. Investigate alternative detectors (e.g., YOLOv8m, Faster R-CNN, or domain-specific models)")
    print("  4. Consider camera placement or scene-specific fine-tuning if labeled data is available")
    print("  5. Evaluate whether the missed detections are due to occlusion, scale, or domain mismatch")
    print()
    print("Limitations of Current Evaluation:")
    print("  - Only 12 frames from a single video")
    print("  - No bounding box annotations (person-level metrics unavailable)")
    print("  - Single camera angle and lighting condition")
    print("  - Small sample size limits statistical significance")
    print("  - Results are not generalizable to deployment conditions")
    print()


if __name__ == "__main__":
    main()
