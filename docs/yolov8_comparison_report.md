# Part 4 Person Detection Improvement: YOLOv8n vs YOLOv8s Comparison Report

**Date:** 2026-10-19
**Repository:** `/home/rudrakshi/sih-attendance-monitoring`
**Branch:** master
**Task:** Compare YOLOv8s against YOLOv8n for Part 4 person detection accuracy

---

## Executive Summary

A controlled experiment compared pretrained YOLOv8n (baseline) against YOLOv8s on the same test video and sampled frames. YOLOv8s showed modest count-level improvement (MAE 0.583 → 0.417) but incurred a 1.62x latency increase. Neither model achieved acceptable reliability: YOLOv8s still missed 5 of 8 visible people, and exact count agreement remained unchanged at 8/12 frames.

**Recommendation:** Keep YOLOv8n as the production baseline. Do not adopt YOLOv8s.

---

## 1. Repository and Initial State

### Git Status
- **Branch:** master
- **Modified files:** 13 existing files (README, config, models, routes, schemas, tests, docs)
- **New files:** 11 Part 4 implementation files (detector, processor, routes, tests, scripts, docs)
- **Model weights:** `yolov8n.pt` (6.5 MB) and `yolov8s.pt` (21.5 MB) present in backend directory
- **Uncommitted changes:** All Part 4 implementation preserved; no resets or cleanups performed

### Environment
- **Python:** 3.10.12
- **PyTorch:** 2.14.1+cpu
- **Ultralytics:** 8.3.40
- **OpenCV:** 4.11.0
- **NumPy:** 1.26.4
- **Database:** PostgreSQL with existing `occupancy_frames` and `video_quality_samples` tables

### Test Video
- **Upload ID:** `469a642f-8699-41d9-ac19-bc485eb3e86e`
- **File:** `phd_room.mp4`
- **Resolution:** 1280x720
- **FPS:** 30
- **Duration:** ~118 seconds
- **Status:** Part 3 quality assessment completed (USABLE, 12 samples at 10s interval)

---

## 2. Baseline Reproduction (YOLOv8n)

### Configuration
- **Model:** yolov8n.pt (local weights)
- **Class:** COCO person (class ID 0)
- **Confidence threshold:** 0.25
- **IoU NMS threshold:** 0.45
- **Image size:** 640
- **Device:** CPU
- **Sample interval:** 10 seconds

### Results on 12 Sampled Frames

| Time (s) | Manual Count | YOLOv8n Count | Error | Status |
|----------|--------------|---------------|-------|--------|
| 0.0 | 2 | 0 | 2 | False zero |
| 10.0 | 1 | 1 | 0 | Correct |
| 20.0 | 2 | 0 | 2 | False zero |
| 30.0 | 1 | 0 | 1 | False zero |
| 40.0 | 0 | 0 | 0 | Correct |
| 50.0 | 0 | 0 | 0 | Correct |
| 60.0 | 0 | 0 | 0 | Correct |
| 70.0 | 0 | 0 | 0 | Correct |
| 80.0 | 0 | 0 | 0 | Correct |
| 90.0 | 0 | 0 | 0 | Correct |
| 100.0 | 0 | 0 | 0 | Correct |
| 110.0 | 2 | 0 | 2 | False zero |

### Baseline Metrics
- **Count MAE:** 0.583
- **Exact count agreement:** 8/12 (66.7%)
- **False-zero frames:** 4/12 (33.3%)
- **False-positive frames:** 0/12
- **Avg inference latency (steady-state):** 60.72 ms/frame
- **Peak memory:** 64.85 MB

**Verification:** Baseline results match the documented evaluation in `docs/person_detection_evaluation.md`.

---

## 3. YOLOv8s Comparison

### Configuration
Identical to YOLOv8n except:
- **Model:** yolov8s.pt (pretrained, 21.5 MB)
- All other parameters unchanged (conf=0.25, iou=0.45, imgsz=640, CPU)

### Results on 12 Sampled Frames

| Time (s) | Manual Count | YOLOv8n Count | YOLOv8s Count | v8n Error | v8s Error | Better |
|----------|--------------|---------------|---------------|-----------|-----------|--------|
| 0.0 | 2 | 0 | 0 | 2 | 2 | Tie |
| 10.0 | 1 | 1 | 1 | 0 | 0 | Tie |
| 20.0 | 2 | 0 | 1 | 2 | 1 | v8s |
| 30.0 | 1 | 0 | 0 | 1 | 1 | Tie |
| 40.0 | 0 | 0 | 0 | 0 | 0 | Tie |
| 50.0 | 0 | 0 | 0 | 0 | 0 | Tie |
| 60.0 | 0 | 0 | 0 | 0 | 0 | Tie |
| 70.0 | 0 | 0 | 0 | 0 | 0 | Tie |
| 80.0 | 0 | 0 | 0 | 0 | 0 | Tie |
| 90.0 | 0 | 0 | 0 | 0 | 0 | Tie |
| 100.0 | 0 | 0 | 0 | 0 | 0 | Tie |
| 110.0 | 2 | 0 | 1 | 2 | 1 | v8s |

### YOLOv8s Metrics
- **Count MAE:** 0.417 (28.6% improvement over v8n)
- **Exact count agreement:** 8/12 (unchanged)
- **False-zero frames:** 2/12 (reduced from 4)
- **False-positive frames:** 0/12
- **Avg inference latency (steady-state):** 98.37 ms/frame
- **Peak memory:** 1.63 MB

### Detailed Detections

**YOLOv8s recovered:**
- 20s: 1 person detected (conf=0.3334), box=[508, 233, 578, 396]
- 110s: 1 person detected (conf=0.3555), box=[898, 245, 978, 475]

**YOLOv8s still missed:**
- 0s: 2 people (both models returned 0)
- 20s: 1 person (detected 1 of 2)
- 30s: 1 person (both models returned 0)
- 110s: 1 person (detected 1 of 2)

**Total missed people by YOLOv8s:** 5 of 8 visible people

---

## 4. Resource Usage Comparison

| Metric | YOLOv8n | YOLOv8s | Ratio (s/n) |
|--------|---------|---------|-------------|
| Avg inference latency | 60.72 ms | 98.37 ms | 1.62x |
| Peak memory | 64.85 MB | 1.63 MB | 0.03x |

**Note:** Peak memory for YOLOv8n includes model loading overhead on first frame. Steady-state memory usage is similar (~1.4 MB) for both models. The 1.62x latency increase is the primary resource cost.

**Practical impact:** For a 2-hour video at 10s sampling (~720 frames):
- YOLOv8n: ~44 seconds total inference time
- YOLOv8s: ~71 seconds total inference time
- Difference: +27 seconds per video

---

## 5. Ground Truth Coverage and Limitations

### Current Ground Truth
- **Source:** Manual visual inspection documented in `docs/person_detection_evaluation.md`
- **Frames:** 12 frames from a single video (`phd_room.mp4`)
- **Coverage:** 5 occupied frames (8 visible people), 7 empty frames
- **Annotations:** Count-level only; no bounding boxes
- **Status:** Documented in `docs/person_detection_ground_truth.md`

### Limitations
1. **Small sample size:** 12 frames from one video is insufficient for generalizable conclusions
2. **No bounding boxes:** Person-level precision/recall/F1 cannot be computed
3. **Single camera angle:** One viewpoint; other classroom layouts may differ
4. **Single lighting condition:** One recording; daylight, evening, artificial lighting not tested
5. **Limited temporal coverage:** 10-second sampling may miss transient presence
6. **No diversity:** No occlusion levels, person scales, or edge cases represented

### Evaluation Metrics Computed
- ✅ Count MAE
- ✅ Median absolute error
- ✅ Exact count agreement
- ✅ False-zero frames
- ✅ False-positive frames
- ❌ Person-level precision/recall/F1 (requires bounding boxes)
- ❌ Duplicate detection analysis (requires bounding boxes)

---

## 6. Software Behavior and Regression Tests

### Test Results
- **Part 4 tests:** 15/15 passed
- **Full backend test suite:** 60/60 passed
- **Git diff-check:** No whitespace or trailing space issues

### Test Coverage
- Detector confidence filtering and NMS
- Unusable frame handling (null counts, not zero)
- Evidence generation (optional, bounded)
- API idempotency (repeat processing replaces rows)
- Missing video and validation errors
- Quality assessment dependency
- Globally unusable footage skips detector
- Inference failure persists null count
- Migration script idempotency

### Confirmed Invariants
- ✅ Unusable frames are not recorded as zero-person counts
- ✅ Failed inference results in null `person_count`
- ✅ Quality status semantics preserved
- ✅ No duplicate records on repeat processing
- ✅ Evidence generation bounded and optional
- ✅ No identity tracking or face recognition

### Code Inspection Findings
- **No software defects confirmed:** The wrapper logic, confidence filtering, class filtering, and NMS behave as configured
- **No double NMS issue:** Ultralytics applies NMS, then the wrapper applies OpenCV NMS; this is intentional for safety
- **No counting bug:** The count correctly reflects the number of post-NMS detections
- **Issue is model limitation:** Missed detections are due to model capacity/scene mismatch, not code bugs

---

## 7. Files Changed

### New Files Created (Evaluation Scripts)
1. `backend/scripts/reproduce_baseline.py` - Reproduces YOLOv8n baseline on test video
2. `backend/scripts/compare_models.py` - Compares YOLOv8n vs YOLOv8s fairly
3. `backend/scripts/evaluate_detector.py` - Evaluation utilities (IoU, matching, metrics)
4. `backend/scripts/comprehensive_evaluation.py` - Comprehensive analysis and reporting
5. `docs/person_detection_ground_truth.md` - Ground truth documentation

### Modified Files
1. `backend/.gitignore` - Added `*.pt` and `weights/` to exclude model weights from Git

### Files Preserved (No Changes)
- All Part 4 implementation files unchanged
- Production configuration unchanged (conf=0.25, iou=0.45, imgsz=640, yolov8n.pt)
- All existing tests unchanged
- All existing functionality preserved

---

## 8. Decision: Keep YOLOv8n

### Recommendation
**Keep YOLOv8n as the production baseline. Do not adopt YOLOv8s.**

### Rationale

1. **Marginal accuracy improvement:**
   - Count MAE improved from 0.583 to 0.417 (28.6% relative)
   - False-zero frames reduced from 4 to 2
   - However, exact count agreement unchanged at 8/12
   - 5 of 8 visible people still missed by YOLOv8s

2. **Model limitation persists:**
   - YOLOv8s recovers only 2 of 7 previously missed people
   - Both models miss the same difficult cases (0s, 30s)
   - The improvement does not reach a reliability threshold for occupancy decisions

3. **Resource cost significant:**
   - 1.62x latency increase (61ms → 98ms per frame)
   - For a 2-hour video: +27 seconds processing time
   - CPU-only deployment makes latency a practical concern

4. **No operational justification:**
   - Neither model meets acceptable reliability
   - The marginal improvement does not warrant the latency cost
   - Switching models does not solve the underlying detection problem

### What This Decision Means
- **Production defaults remain:** `PERSON_DETECTOR_MODEL=yolov8n.pt`, conf=0.25, iou=0.45, imgsz=640
- **No code changes required:** Existing implementation is correct
- **YOLOv8s weights retained:** Available for future evaluation if needed
- **Evaluation scripts available:** Can be reused for expanded testing

---

## 9. Remaining Risks and Next Steps

### Current Risks
1. **Low detection reliability:** Neither model reliably detects visible people (5/8 missed by v8s)
2. **Limited evaluation:** 12 frames from one video is insufficient for deployment decisions
3. **No person-level metrics:** Cannot compute precision/recall without bounding boxes
4. **Unknown generalization:** Performance on other cameras/lighting/angles is unknown

### Recommended Next Steps

**Immediate (before Part 5):**
1. **Expand evaluation set:**
   - Collect 30+ frames across multiple videos
   - Include diverse cameras, lighting conditions, and angles
   - Add edge cases (near/far people, partial occlusion, crowded scenes)

2. **Annotate bounding boxes:**
   - Manually annotate all visible people with pixel coordinates
   - Compute person-level precision, recall, F1 at IoU 0.50 and 0.75
   - Distinguish missed detections from localization errors

3. **Evaluate alternative detectors:**
   - Test YOLOv8m (medium size, better accuracy/vs latency tradeoff)
   - Consider Faster R-CNN or other two-stage detectors for small/occluded people
   - Evaluate domain-specific models if available

4. **Investigate scene-specific factors:**
   - Analyze whether camera placement or viewpoint causes misses
   - Evaluate if partial occlusion (monitors, doorways) is the primary issue
   - Assess person scale relative to image resolution

**Long-term (if accuracy remains inadequate):**
5. **Fine-tuning:**
   - Assess labeled-data requirements for camera-specific fine-tuning
   - Evaluate validation strategy and resource needs
   - Consider transfer learning from COCO to deployment scenes

6. **Multi-model ensembling:**
   - Combine multiple detectors to improve recall
   - Evaluate ensemble latency and complexity

7. **Temporal aggregation:**
   - Use tracking (ByteTrack) to aggregate detections across frames
   - **Note:** Tracking is not a substitute for single-frame detection; fix detection first

### What NOT to Do
- ❌ Do not use current counts for attendance decisions
- ❌ Do not start Part 5 until Part 4 reliability is acceptable
- ❌ Do not add tracking to compensate for detection misses
- ❌ Do not repeatedly tune thresholds on the same small evaluation set
- ❌ Do not assume YOLOv8m will solve the problem without evidence

---

## 10. Part 4 Acceptance Review

### Software Behavior
- ✅ Correct: All regression tests pass (60/60)
- ✅ Correct: Unusable frames recorded as null, not zero
- ✅ Correct: Failed inference persists null count
- ✅ Correct: No duplicate records on repeat processing
- ✅ Correct: Evidence generation optional and bounded
- ✅ Correct: No identity tracking or face recognition

### Evaluation Evidence
- ✅ Reproducible: Baseline reproduced exactly as documented
- ✅ Controlled: YOLOv8s compared with identical configuration
- ✅ Measured: Count-level metrics computed properly
- ⚠️ Limited: Only 12 frames from one video
- ⚠️ Limited: No bounding box annotations (person-level metrics unavailable)

### Configuration Justification
- ✅ Evidence-based: Decision based on measured metrics, not assumptions
- ✅ Resource-aware: Latency cost considered for CPU deployment
- ✅ Conservative: No changes without clear benefit
- ✅ Honest: Model limitations documented, not hidden

### Resource Usage
- ✅ Acceptable: YOLOv8n latency (~61ms/frame) is reasonable for CPU
- ✅ Memory: Peak memory (~65MB) is acceptable for 16 GB RAM
- ✅ Scalable: Can process 2-hour videos in ~44 seconds

### Remaining Limitations
- ⚠️ Accuracy: Neither model meets reliability threshold
- ⚠️ Coverage: Evaluation set too small for generalization
- ⚠️ Metrics: Person-level precision/recall not computed
- ⚠️ Generalization: Unknown performance on other cameras/scenes

### Overall Status
**Part 4 is NOT ready for Part 5 progression.**

The software implementation is correct, but the detection accuracy is insufficient for operational use. The recommended next steps (expanded evaluation, bounding box annotation, alternative detectors) must be completed before Part 5 can begin.

---

## 11. Appendix: Command Reference

### Reproduce Baseline
```bash
cd backend
venv/bin/python scripts/reproduce_baseline.py
```

### Compare Models
```bash
cd backend
venv/bin/python scripts/compare_models.py
```

### Comprehensive Evaluation
```bash
cd backend
venv/bin/python scripts/comprehensive_evaluation.py
```

### Run Tests
```bash
cd backend
venv/bin/python -m pytest tests/test_person_detection.py -v
venv/bin/python -m pytest tests/ -v
```

### Check Git Status
```bash
git status
git diff --check
```

---

**Report prepared by:** Devin AI Agent
**Date:** 2026-10-19
**Repository:** `/home/rudrakshi/sih-attendance-monitoring`
**Branch:** master
