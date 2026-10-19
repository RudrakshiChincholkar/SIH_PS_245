# Ground Truth Annotations for Person Detection Evaluation

## Upload ID
`469a642f-8699-41d9-ac19-bc485eb3e86e`

## Video Metadata
- File: `phd_room.mp4`
- Resolution: 1280x720
- FPS: 30
- Total frames: 3548
- Duration: ~118 seconds

## Sample Interval
10 seconds (production default)

## Ground Truth Labels (Count-Level)

These labels are based on manual visual inspection documented in `person_detection_evaluation.md`. Person-level bounding boxes are not yet annotated; only frame-level counts are available.

| Sample Index | Timestamp (s) | Frame Index | Manual Count | Notes |
|-------------|---------------|-------------|--------------|-------|
| 0 | 0.0 | 0 | 2 | Two partially occluded people: one in rear doorway, one behind right-side monitors |
| 1 | 10.0 | 300 | 1 | One clearly visible person in middle of room |
| 2 | 20.0 | 600 | 2 | Two visible people in middle of room |
| 3 | 30.0 | 900 | 1 | One person at rear doorway |
| 4 | 40.0 | 1200 | 0 | No visible people |
| 5 | 50.0 | 1500 | 0 | No visible people |
| 6 | 60.0 | 1800 | 0 | No visible people |
| 7 | 70.0 | 2100 | 0 | No visible people |
| 8 | 80.0 | 2400 | 0 | No visible people |
| 9 | 90.0 | 2700 | 0 | No visible people |
| 10 | 100.0 | 3000 | 0 | No visible people |
| 11 | 110.0 | 3300 | 2 | Two people walking through the room |

## Total Ground Truth Statistics
- Total frames evaluated: 12
- Occupied frames (count > 0): 5
- Empty frames (count = 0): 7
- Total visible people: 8

## Limitations
- **No bounding box annotations**: Person-level precision/recall cannot be computed without manually annotated boxes
- **Single video**: This is a small exploratory sample from one recording, not representative of deployment diversity
- **Single camera angle**: Only one viewpoint is evaluated; other classroom layouts may have different detection characteristics
- **Limited temporal coverage**: 10-second sampling may miss transient presence between samples

## Next Steps for Comprehensive Evaluation
1. Annotate bounding boxes for all 8 visible people across the 5 occupied frames
2. Expand the evaluation set to include:
   - Multiple recordings from different classrooms
   - Different lighting conditions (daylight, evening, artificial)
   - Different camera angles and distances
   - Frames with varying occlusion levels
   - Edge cases (people near edges, partial visibility, etc.)
3. Compute person-level metrics:
   - Precision, recall, F1 at IoU thresholds 0.50 and 0.75
   - Missed detection rate
   - False positive rate
   - Duplicate detection analysis
4. If needed, split into validation and test sets for threshold tuning

## Current Evaluation Status
Count-level evaluation is complete. Person-level evaluation requires bounding box annotations.
