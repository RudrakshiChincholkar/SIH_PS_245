# Person Detector Evaluation Procedure

No detector accuracy claim is made until counts are measured against labelled frames from the deployment camera angles. Keep this evaluation separate from attendance records and do not use face or identity labels.

## Label a small sample

1. Select at least 30 frames across representative daylight, evening, partially occluded, near/far, and empty-room conditions. Include usable and unusable footage but do not label counts for frames the quality pipeline marks unusable.
2. Record each frame's source upload ID and timestamp. Manually label the visible person count. For a smaller missed-detection analysis, also annotate one bounding box per visible person using pixel coordinates `(x1, y1, x2, y2)`.
3. Run Part 3 and Part 4 using the same sample interval. Join predictions and labels by upload ID and timestamp (allow at most half a frame interval for timestamp rounding).
4. Exclude unusable frames from count-error metrics and report their number separately. A null predicted count is missing evidence, not a predicted zero.

A simple CSV layout is:

```csv
upload_id,timestamp_seconds,ground_truth_count,gt_boxes,predicted_count,predicted_boxes,frame_status
<registered-upload-id>,0.0,2,"[[10,20,40,90],[80,15,110,95]]",2,"[[11,19,41,91],[79,16,109,94]]",USABLE
```

Replace the example row with labels and actual API output; it is a format example, not a measured result.

## Report

For each usable labelled frame, calculate absolute count error:

`absolute_count_error = abs(predicted_count - ground_truth_count)`

Report mean absolute error, median absolute error, exact-count agreement (`predicted_count == ground_truth_count`), number of evaluated frames, and number of skipped/unusable frames. Do not combine skipped frames with zero-count predictions.

When ground-truth boxes are labelled, match predicted person boxes to ground-truth boxes one-to-one at intersection-over-union (IoU) >= 0.50. Unmatched ground-truth boxes are missed detections (false negatives); unmatched predicted boxes are false positives. Report total missed detections, false positives, and number of labelled people. If only counts are labelled, missed detections cannot be distinguished from localization errors or false positives; report count error only.

Keep the labelled fixture under controlled access if it contains real people. Automated tests use synthetic frames and mocked detector outputs, never real CCTV footage or downloaded model weights.

## Initial six-frame review (superseded)

This section is retained as investigation history. Its conclusions are superseded by the full 12-frame experiment below.

Reviewed on 2026-10-19 from the source frames at the exact Part 4 sequential sample indices (recording reports 30 FPS; timestamps 0, 10, 20, 50, 80, and 110 seconds correspond to frame indices 0, 300, 600, 1500, 2400, and 3300). Counts below are manually judged from those six images, not derived from detector output. At 0 seconds, two partially occluded people are visually discernible: one in the rear doorway and one partly behind the right-side monitors. At 20 seconds, two people are visible in the middle of the room. The sampled frames at 50, 80, and 110 seconds appear empty. This is a small exploratory sample, not a representative accuracy evaluation.

| Timestamp | Manually reviewed count | YOLO `.25` | YOLO `.10` | YOLO `.05` | Review / estimated misses |
| ---: | ---: | ---: | ---: | ---: | --- |
| 0s | 2 | 0 | 0 | 0 | Two partially occluded people missed at all tested thresholds. |
| 10s | 1 | 1 | 1 | 1 | Detected at confidence `0.7797`; no visible person missed. |
| 20s | 2 | 0 | 1 | 2 | At `.10`, one person recovered at `0.1807`, one still missed. At `.05`, the additional `0.062` box substantially overlaps the `.1807` box on the same visible person; the other visible person remains missed. This likely explains the apparent count match at `.05` as a duplicate, not improved recall. |
| 50s | 0 | 0 | 0 | 0 | No visible people in the reviewed frame. |
| 80s | 0 | 0 | 0 | 0 | No visible people in the reviewed frame. |
| 110s | 0 | 0 | 0 | 0 | No visible people in the reviewed frame. |

Count-only summary on these six frames: mean absolute count error was `0.667` at `.25`, `0.500` at `.10`, and `0.333` at `.05`; exact count agreement was 4/6, 4/6, and 5/6 respectively. These count metrics conceal the duplicate at `.05`: by visual one-to-one matching, approximately 4, 3, and 3 of the 5 visible people were missed at `.25`, `.10`, and `.05`. The `.05` result also appears to add a duplicate box on the person at 20 seconds. Exact detection precision/recall is not claimed because manually labelled boxes and IoU matching were not prepared for this quick review.

### Controlled inference settings

The experiment loaded the same local pretrained `yolov8n.pt` once and ran on CPU at the six exact sequential frames. It held COCO class filter `person` (class ID 0), IoU NMS threshold `0.45`, and Ultralytics' default preprocessing and image size (`imgsz=640`, letterbox) constant; only `conf` changed among `.25`, `.10`, and `.05`. The production setting remains `.25`. Results at 10 seconds exactly reproduced the stored production box/confidence. Lowering confidence did not change the zero candidates at 0 seconds, so confidence filtering is not the cause of that miss. At 20 seconds, `.05` retained two overlapping boxes whose approximate IoU is below the configured `.45` NMS cutoff, allowing a duplicate candidate to remain.

### Interpretation and limitations

- **Observed:** At 0 seconds, the reviewed source image visibly contains two partially occluded people, but no person candidates are returned even at `.05`. Therefore the usable-frame zero is a confirmed visual false negative for this reviewed frame.
- **Observed:** At 20 seconds, lowering confidence increases candidates but does not recover the second visible person; the `.05` result includes two boxes over substantially the same person.
- **Plausible causes, not isolated experimentally:** partial occlusion by monitors/doorway, small or low-contrast visible body regions, a high/oblique camera viewpoint, and YOLOv8n's limited capacity for small/occluded people. The experiment does not establish which factor dominates.
- **Sampling limitation:** only one frame per 10 seconds is inspected. Brief movement between samples may be absent from both quality and occupancy samples; this investigation did not change the sampling schedule.
- **Source overlay limitation:** the video itself contains colored rectangles. They are already present in the decoded source and are not reliable ground truth or YOLO output. Only the explicit `YOLO person count` stamp and stored per-person confidence boxes are generated by this system.
- **Evaluation limitation:** the manual set has six frames from one recording and no annotated ground-truth boxes. Counts at those timestamps are a small visual review, not evidence of general model accuracy. Keep unusable frames separate; this reviewed set contains only Part 3 usable samples.

## Full sequential-sample investigation (supersedes the six-frame summary above)

On 2026-10-19, all 12 source samples from upload `469a642f-8699-41d9-ac19-bc485eb3e86e` were decoded sequentially using the production sampling rule. Video metadata was 30 FPS, 1280x720, 3548 reported frames. The sample timestamps and exact decoded frame indices were `0/0`, `10/300`, `20/600`, `30/900`, `40/1200`, `50/1500`, `60/1800`, `70/2100`, `80/2400`, `90/2700`, `100/3000`, and `110/3300` (seconds / frame index). Manual labels below were assigned by viewing the source frames, independently of predictions. Each visible person was counted once; these are frame-level counts, not tracked identities.

| Time | Source index | Manually reviewed count | `.25/.45/640` | `.10/.45/640` | `.05/.45/640` | Review |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0s | 0 | 2 | 0 | 0 | 0 | Two partly occluded people, doorway and behind monitors. |
| 10s | 300 | 1 | 1 | 1 | 1 | One clearly visible person; score `0.7797`. |
| 20s | 600 | 2 | 0 | 1 | 2 | Two visible people. `.05` returns two overlapping boxes on one person, not one box per person. |
| 30s | 900 | 1 | 0 | 0 | 0 | One person at rear doorway; missed at all tested confidence values. |
| 40s | 1200 | 0 | 0 | 0 | 0 | No visible people. |
| 50s | 1500 | 0 | 0 | 0 | 0 | No visible people. |
| 60s | 1800 | 0 | 0 | 0 | 0 | No visible people. |
| 70s | 2100 | 0 | 0 | 0 | 0 | No visible people. |
| 80s | 2400 | 0 | 0 | 0 | 0 | No visible people. |
| 90s | 2700 | 0 | 0 | 0 | 0 | No visible people. |
| 100s | 3000 | 0 | 0 | 0 | 0 | No visible people. |
| 110s | 3300 | 2 | 0 | 0 | 0 | Two people walking through the room; missed at all tested confidence values. |

The reviewed set contains eight manually visible people across five occupied frames. Count-only results:

| Setting | Count MAE | Exact frame-count agreement | Count-level missed people | Count-level extras |
| --- | ---: | ---: | ---: | ---: |
| Baseline `.25/.45/640` | `0.583` (7/12 total absolute error) | 8/12 | 7 | 0 |
| Confidence `.10/.45/640` | `0.500` (6/12) | 8/12 | 6 | 0 |
| Confidence `.05/.45/640` | `0.417` (5/12) | 9/12 | 5 | 0 |
| Confidence `.05`, IoU `.25`, `imgsz=640` | `0.500` (6/12) | 8/12 | 6 | 0 |
| Baseline confidence, `imgsz=960` | `0.583` (7/12) | 8/12 | 7 | 0 |
| Baseline confidence, `imgsz=1280` | `0.583` (7/12) | 8/12 | 7 | 0 |

Count metrics do not describe person-level precision/recall. At `.05`, the 20-second count equals ground truth numerically, but one of its two boxes is a duplicate over the first visible person and the second visible person is still missed. Thus the `.05` run still misses six distinct people and has one likely duplicate box; the lower count MAE is not evidence of a reliable detector. Formal person-level precision/recall is not reported because ground-truth bounding boxes were not annotated for all eight people.

### Experimental controls and runtime

Runtime used Ultralytics `8.3.40`, PyTorch `2.14.1+cpu`, local `yolov8n.pt`, CPU inference, COCO `classes=[0]`, and the same 12 sequentially decoded frames. Ultralytics' default `imgsz=640` and letterbox preprocessing were retained except for the explicit image-size rows. Each setting was warmed once, then the same 12 frames were run. Confidence experiment changed only confidence (`.25`, `.10`, `.05`), keeping IoU `.45` and `imgsz=640`. NMS experiment changed only IoU to `.25` from `.45` at confidence `.05`. Image-size experiment changed only `imgsz` to 960 and 1280, keeping confidence `.25` and IoU `.45`.

| Configuration | Wall ms/frame | Process CPU seconds / 12 frames | RSS after run | Process peak RSS |
| --- | ---: | ---: | ---: | ---: |
| `.25/.45/640` | 35.9 | 3.472 | 498.6 MB | 506.1 MB |
| `.10/.45/640` | 35.8 | 3.432 | 505.4 MB | 506.1 MB |
| `.05/.45/640` | 35.2 | 3.376 | 505.0 MB | 506.1 MB |
| `.05/.25/640` | 34.4 | 3.296 | 505.4 MB | 506.1 MB |
| `.25/.45/960` | 68.0 | 6.535 | 516.0 MB | 538.0 MB |
| `.25/.45/1280` | 114.0 | 10.939 | 606.9 MB | 621.8 MB |

CPU time exceeds wall time because Torch uses multiple CPU threads. These are one-run laptop measurements, not benchmark-grade. Peak RSS is process high-water memory; later rows include any retained allocator/model memory from earlier rows. Larger image sizes approximately double/triple latency and increased measured memory, but did not change any frame count or recover a missed person.

### Confirmed behavior and causes

- The zero at 0 seconds is a confirmed visual false negative: two partially occluded people are visible in the decoded frame, and all three confidence values return no person candidate.
- At 30 and 110 seconds, one and two visually apparent people respectively are also missed at all tested confidence values. This demonstrates misses beyond the initial 0-second example.
- At 20 seconds, `.05/.45` returns boxes with confidence `0.1807` and `0.062`. Their measured IoU is approximately `0.287`, below NMS IoU `.45`; therefore both Ultralytics NMS and the wrapper's second OpenCV NMS correctly leave them. At IoU `.25`, they reduce to one box, but this still misses one of the two visible people. The duplicate is a low-confidence localization/NMS-threshold behavior, not a class-filter bug.
- All returned candidates in this sample are class 0 because the detector passes `classes=[0]`, then checks class ID 0 again. Confidence filtering behaves as configured. No wrong-class candidate was observed.
- Plausible contributors include partial occlusion at 0/30 seconds, changing person scale/occlusion in the room, high camera viewpoint, and this small model's scene mismatch. At 110 seconds two people are relatively visible and still missed, so occlusion alone cannot explain all failures. The experiment did not isolate training-domain/model-capacity causes.
- The 10-second sampling strategy is unchanged. A single frame per interval can miss transient presence between samples; this run makes no claim about unsampled time.

### Configuration decision

Keep the production settings unchanged at confidence `.25`, IoU `.45`, and `imgsz=640`. The `.10` variant recovers only the candidate at 20 seconds and still misses six visible people. The `.05` variant has the lowest count MAE but its apparent count recovery at 20 seconds is a duplicate box, while misses remain at 0, 30, and 110 seconds. Lowering confidence is therefore not a justified reliability fix. Stricter IoU removes the duplicate but also leaves a miss; larger image sizes add CPU and memory cost without recovering people. No tested configuration meets a reasonable reliability criterion for occupancy decisions.

Recommended next investigation: collect manually boxed labels from multiple representative videos/cameras, then evaluate person-level IoU precision/recall and missed-person rate before comparing a larger model or camera-specific fine-tuning. Do not use current frame counts for attendance decisions. Unusable/decode/inference-failed frames remain null, not zero.
