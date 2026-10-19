"""Evaluate detector predictions against ground truth annotations."""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np


def compute_iou(box1: List[float], box2: List[float]) -> float:
    """Compute Intersection over Union for two bounding boxes in [x1, y1, x2, y2] format."""
    x1_inter = max(box1[0], box2[0])
    y1_inter = max(box1[1], box2[1])
    x2_inter = min(box1[2], box2[2])
    y2_inter = min(box1[3], box2[3])

    if x2_inter <= x1_inter or y2_inter <= y1_inter:
        return 0.0

    inter_area = (x2_inter - x1_inter) * (y2_inter - y1_inter)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union_area = box1_area + box2_area - inter_area

    return inter_area / union_area if union_area > 0 else 0.0


def match_boxes_one_to_one(
    gt_boxes: List[List[float]],
    pred_boxes: List[List[float]],
    iou_threshold: float = 0.5,
) -> Tuple[List[int], List[int], List[Tuple[int, int, float]]]:
    """
    Match predicted boxes to ground truth boxes using greedy one-to-one matching at IoU threshold.

    Returns:
        unmatched_gt_indices: list of GT box indices with no match
        unmatched_pred_indices: list of predicted box indices with no match
        matches: list of (gt_idx, pred_idx, iou) tuples for matched pairs
    """
    if not gt_boxes and not pred_boxes:
        return [], [], []

    if not gt_boxes:
        return [], list(range(len(pred_boxes))), []

    if not pred_boxes:
        return list(range(len(gt_boxes))), [], []

    # Compute IoU matrix
    iou_matrix = np.zeros((len(gt_boxes), len(pred_boxes)))
    for i, gt_box in enumerate(gt_boxes):
        for j, pred_box in enumerate(pred_boxes):
            iou_matrix[i, j] = compute_iou(gt_box, pred_box)

    # Greedy matching: always pick the highest IoU pair above threshold
    matched_gt = set()
    matched_pred = set()
    matches = []

    while True:
        # Find highest IoU pair
        max_iou = 0.0
        best_gt = -1
        best_pred = -1

        for i in range(len(gt_boxes)):
            if i in matched_gt:
                continue
            for j in range(len(pred_boxes)):
                if j in matched_pred:
                    continue
                if iou_matrix[i, j] > max_iou:
                    max_iou = iou_matrix[i, j]
                    best_gt = i
                    best_pred = j

        if max_iou < iou_threshold or best_gt == -1 or best_pred == -1:
            break

        matches.append((best_gt, best_pred, float(max_iou)))
        matched_gt.add(best_gt)
        matched_pred.add(best_pred)

    unmatched_gt = [i for i in range(len(gt_boxes)) if i not in matched_gt]
    unmatched_pred = [j for j in range(len(pred_boxes)) if j not in matched_pred]

    return unmatched_gt, unmatched_pred, matches


def evaluate_count_level(
    predictions: List[Dict[str, Any]],
    ground_truth: Dict[float, int],
) -> Dict[str, Any]:
    """Evaluate count-level metrics."""
    abs_errors = []
    exact_agreements = 0
    false_zeros = 0
    false_positives = 0

    for pred in predictions:
        timestamp = pred["timestamp"]
        pred_count = pred["count"]
        gt_count = ground_truth.get(timestamp)

        if gt_count is None:
            continue

        error = abs(pred_count - gt_count)
        abs_errors.append(error)

        if pred_count == gt_count:
            exact_agreements += 1

        if gt_count > 0 and pred_count == 0:
            false_zeros += 1

        if gt_count == 0 and pred_count > 0:
            false_positives += 1

    return {
        "mae": np.mean(abs_errors) if abs_errors else None,
        "median_ae": np.median(abs_errors) if abs_errors else None,
        "exact_agreement": exact_agreements,
        "total_frames": len(abs_errors),
        "false_zeros": false_zeros,
        "false_positives": false_positives,
    }


def evaluate_box_level(
    predictions: List[Dict[str, Any]],
    ground_truth_boxes: Dict[float, List[List[float]]],
    iou_threshold: float = 0.5,
) -> Dict[str, Any]:
    """
    Evaluate person-level metrics using bounding box matching.

    Args:
        predictions: list of prediction dicts with 'timestamp', 'detections' (list of {'box': [...], 'confidence': ...})
        ground_truth_boxes: dict mapping timestamp to list of GT boxes
        iou_threshold: IoU threshold for positive match

    Returns:
        dict with precision, recall, F1, missed_detections, false_positives, etc.
    """
    total_gt = 0
    total_pred = 0
    total_matches = 0
    missed_detections = 0
    false_positives = 0

    for pred in predictions:
        timestamp = pred["timestamp"]
        gt_boxes = ground_truth_boxes.get(timestamp, [])
        pred_boxes = [d["box"] for d in pred.get("detections", [])]

        total_gt += len(gt_boxes)
        total_pred += len(pred_boxes)

        unmatched_gt, unmatched_pred, matches = match_boxes_one_to_one(
            gt_boxes, pred_boxes, iou_threshold
        )

        total_matches += len(matches)
        missed_detections += len(unmatched_gt)
        false_positives += len(unmatched_pred)

    precision = total_matches / total_pred if total_pred > 0 else 0.0
    recall = total_matches / total_gt if total_gt > 0 else 0.0
    f1 = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "total_gt_people": total_gt,
        "total_pred_detections": total_pred,
        "true_positives": total_matches,
        "missed_detections": missed_detections,
        "false_positives": false_positives,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "iou_threshold": iou_threshold,
    }


def main():
    """Example usage."""
    # Example count-level evaluation
    predictions = [
        {"timestamp": 0.0, "count": 0},
        {"timestamp": 10.0, "count": 1},
        {"timestamp": 20.0, "count": 0},
        {"timestamp": 30.0, "count": 0},
        {"timestamp": 110.0, "count": 0},
    ]

    ground_truth_counts = {
        0.0: 2,
        10.0: 1,
        20.0: 2,
        30.0: 1,
        110.0: 2,
    }

    count_metrics = evaluate_count_level(predictions, ground_truth_counts)
    print("Count-level metrics:")
    print(json.dumps(count_metrics, indent=2))

    # Example box-level evaluation (when boxes are annotated)
    # predictions_with_boxes = [
    #     {
    #         "timestamp": 10.0,
    #         "detections": [
    #             {"box": [100, 200, 300, 400], "confidence": 0.9},
    #         ]
    #     }
    # ]
    #
    # ground_truth_boxes = {
    #     10.0: [[105, 205, 295, 395]],
    # }
    #
    # box_metrics = evaluate_box_level(predictions_with_boxes, ground_truth_boxes, iou_threshold=0.5)
    # print("\nBox-level metrics:")
    # print(json.dumps(box_metrics, indent=2))


if __name__ == "__main__":
    main()
