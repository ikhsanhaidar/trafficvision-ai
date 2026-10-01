# Annotation and dataset preparation

No labeled training or evaluation dataset is included. Start with a small,
licensed, auditable set before paying for more annotation or compute. The
[smoke fixture](SOURCES.md) provides licensed real traffic footage, but has no
ground truth and is not an accuracy benchmark.

## Provenance and split design

Maintain `data/dataset/manifest.csv` (or a versioned JSON equivalent) with at least:
`video_id`, `camera_id`, `location_group`, `source_path`, `source_sha256`,
`source_url`, `author`, `license`, `license_url`, `split`, `lighting`, `occlusion`,
`density`, `start_pts_seconds`, `end_pts_seconds`, `annotation_version`, `reviewer`.
Record any crop, resize, frame extraction, time trimming or format conversion.
For every extracted image include its relative path, source video ID, source PTS,
image SHA-256 and label-file SHA-256 in an accompanying image inventory. Hash and
version that inventory alongside the manifest. Keep permission/license evidence.

Assign entire videos before extracting frames. Prefer camera/location-disjoint
train, validation and test sets; group adjacent recordings from the same camera
when they overlap in time or share nearly identical conditions. Document whether
the test measures new times at a known camera or generalization to new cameras.
No vehicle trajectory or adjacent near-duplicate frames may straddle splits.
Review hashes and source/time ranges for overlap. There is no universal split
percentage for a tiny dataset: prioritize enough independent videos per condition
to make an interpretable evaluation, and publish the actual counts.

Include bright daytime, low light/night, partial and heavy occlusion, sparse and
dense traffic when available. Record each condition's support. Do not invent
coverage by relabeling a daytime clip as night or treating an augmentation as an
independent test video. Keep a truly empty traffic scene to measure false positives.

## Bounding-box labels

Annotate all visible target vehicles in the selected images, not only objects
near the counting line. Use a consistent visible-box policy, tight axis-aligned
boxes, and a documented policy for partial occlusion, truncated objects, parked
vehicles and ambiguous vans/three-wheelers. Review a subset twice and resolve
disagreements. The labels are `car`, `motorcycle`, `bus`, `truck`; unsupported
subtypes need an explicit documented assignment or exclusion policy.

The [example dataset YAML](../configs/dataset.example.yaml) uses the checkpoint's
COCO vocabulary. Write one object per YOLO text line:

```text
class_id center_x center_y width height
```

Coordinates are normalized by the image dimensions. For this configuration,
`car=2`, `motorcycle=3`, `bus=5`, `truck=7`; do not silently renumber them to 0..3.
Every reviewed empty image has an empty label file. Missing labels must not mean
"not annotated yet" in an evaluation export. Use matching image/label basenames:

```text
data/dataset/
  manifest.csv
  image_inventory.csv
  images/train/camera_a_000010.jpg
  labels/train/camera_a_000010.txt
  images/val/...
  labels/val/...
  images/test/...
  labels/test/...
```

A four-class fine-tuned head is possible, but baseline evaluation against its
0..3 labels requires an explicit ID conversion to the baseline's class indices.
The evaluator rejects incompatible model/dataset vocabularies. Follow the
[official YOLO detection dataset format](https://docs.ultralytics.com/datasets/detect/)
and preserve the mapping with each annotation export.

## Counting events

Annotate the complete reviewed video interval, including frames with no events.
Keep an exact copy of the analysis configuration (normalized ROI and directed
line endpoints) per video in the provenance bundle. Events follow the same
finite-segment, bottom-center convention as the implementation:

1. Let the directed line run from `start=(sx,sy)` to `end=(ex,ey)` in normalized
   image coordinates. Image `x` increases rightward and `y` downward.
2. For the box bottom-center `p`, calculate
   `side=(ex-sx)*(py-sy)-(ey-sy)*(px-sx)`.
   **A** is the negative side; **B** is the positive side. A left-to-right
   horizontal line has A above and B below it.
3. Count a crossing only when the trajectory passes between sides through the
   finite segment and the crossing point is inside the ROI. Movement around an
   endpoint, touching the line and returning, or remaining stationary on the
   line is not a crossing.
4. Mark the physical object's event timestamp at the intersection using adjacent
   **source PTS**, interpolating when appropriate. The application subtracts the
   first decoded frame PTS, so the first frame is video time zero. Do not use
   annotation wall-clock time or `frame_index / nominal_fps` on variable-rate video.
5. Review jitter and short tracks. The algorithm confirms after leaving the
   hysteresis band and reaching minimum track age, but event time refers to the
   earlier intersection. Ground truth follows physical crossings; do not remove
   an obvious event simply because the detector failed to establish a track.

For this MVP, the predicted policy allows each track to count at most once per
line per direction per run. Annotate each physical object at most once per line
per direction for a directly comparable benchmark; record repeat loops/re-entry
separately so this policy's limitation is visible. If a benchmark instead counts
every repeated physical crossing, state that difference explicitly. An ID switch
must not create a new ground-truth object. Assign a stable vehicle class after
reviewing its trajectory, and do not relabel a crossing to match the prediction.

Store ground-truth counting events using the JSON contract in
[EVALUATION.md](EVALUATION.md), including empty `events` arrays. Manual object IDs,
uncertainty flags and review notes belong in the annotation source/manifest; the
counting JSON requires class, line, direction and timestamp only. Review source
identity, line geometry, duration and event completeness before evaluation.

## Optional tracking annotations

IDF1/HOTA need frame-indexed bounding boxes with stable object IDs across occlusion
and a documented visibility/ignore policy. Review identities at crossings and
re-entry. Sampling unrelated frames or storing only crossing events is insufficient.
Keep these labels separate from detection exports; there is no implemented
full-trajectory export/TrackEval adapter in the MVP. Report tracking metrics as
pending until those artifacts and a compatible metric configuration exist.

## Before training

Verify local image paths, complete labels, class IDs, licenses, disjoint source
groups and data hashes. Review representative overlays from every split and
condition. Establish a fixed validation set and a compute/storage budget. Keep
test labels out of parameter selection. Only then run the explicit training
command in [EVALUATION.md](EVALUATION.md); the readiness flag never substitutes
for these checks. Archive the experiment's configuration, logs and checkpoints.
