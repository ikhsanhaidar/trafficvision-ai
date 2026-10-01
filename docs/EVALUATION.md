# Evaluation protocol and report

TrafficVision starts with the pretrained YOLO11n baseline. Project-specific
detection accuracy, counting accuracy, IDF1 and HOTA are **not yet measured**:
no reviewed labeled traffic dataset is bundled. Synthetic tests verify software
behavior. Licensed real-video smoke runs verify execution and output artifacts;
they do not provide accuracy estimates. See [PROGRESS.md](PROGRESS.md) for executed
checks and [MODEL_CARD.md](MODEL_CARD.md) for the baseline's limitations.

## Native CLI functional smoke run (2026-09-30)

One real-video smoke run completed on the development machine. This table records
execution, not detection/counting accuracy or a repeated benchmark distribution.

| Item | Observed value |
| --- | --- |
| Source | Licensed Gothenburg road video, Tomasz Sienicki, CC BY 3.0; checksum in SOURCES.md |
| Source coverage | 1,038 frames, 640×480, 34.599654 seconds, source PTS |
| Hardware | AMD Ryzen 5 6600H, 6 cores / 12 logical CPUs; Windows 11; CPU inference |
| Software | Python 3.12.13, PyTorch 2.8.0+cpu, Ultralytics 8.3.203, PyAV 16.0.1 |
| Model | YOLO11n, SHA-256 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1` |
| Configuration | 640 inference size; 0.25 confidence; all four vehicle classes; empty ROI; line (0.1,0.55)→(0.9,0.55); hysteresis 0.008; minimum age 3; runtime torch threads 8 |
| Pipeline elapsed time | 87.123789 seconds |
| Pipeline throughput | 11.914082 frames/second |
| Mean detection + tracking latency | 75.187 ms/frame (78.044103 seconds / 1,038); arithmetic mean, not p95 |
| Produced events | 27: car A→B 9, car B→A 17, truck B→A 1 |
| Verified artifacts | MP4 fully decodes; frame count/duration retained; JSON/CSV/events consistent; no duplicate track/line/direction keys |
| Accuracy | Not evaluated; no ground truth for this fixture |

The script validates input and loads the model before calling the measured
pipeline, so checkpoint download/model initialization and initial validation are
excluded. Frame processing, overlays, encoding, and output validation are included.
The environment was also doing development work; do not compare this single
measurement to published GPU benchmarks. Re-run on target hardware and report
the same timing scope for comparisons.

Reproduction: `uv run python scripts/smoke_real_video.py --output artifacts/new-smoke-run`.
The output directory must not exist. Machine-readable evidence is stored with
the locally generated `artifacts/real-video-smoke/summary.json` and source attribution;
large media artifacts are intentionally excluded from source control.

## Docker Compose API functional smoke run (2026-10-01)

The same licensed source and analysis configuration completed through the real
HTTP upload, PostgreSQL database, Redis/Celery queue, and CPU worker on Docker
Desktop/WSL2. This is one functional run, not an accuracy estimate or a repeated
benchmark. Its pipeline timing includes the first worker's checkpoint/model setup;
the native CLI measurement above excludes that setup, so their throughput figures
are not directly comparable.

| Item | Observed value |
| --- | --- |
| Source coverage | 1,038 frames, 640x480, 34.599654 seconds, source PTS |
| Hardware | Same Windows 11 AMD Ryzen 5 6600H host; Linux WSL2 container, 12 logical CPUs visible; CPU inference |
| Model | YOLO11n, SHA-256 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1` |
| Configuration | 640 inference size; 0.25 confidence; all four vehicle classes; empty ROI; line (0.1,0.55) to (0.9,0.55); hysteresis 0.008; minimum age 3; runtime torch threads 8 |
| Pipeline elapsed time | 346.717248 seconds |
| Pipeline throughput | 2.993794 frames/second |
| Produced events | 27: car A to B 9, car B to A 17, truck B to A 1 |
| Verified API flow | Upload and preview; queued worker completion; result/events; JSON/CSV export; protected annotated MP4 with HTTP Range; access denied after logout |
| Accuracy | Not evaluated; no ground truth for this fixture |

The pipeline timer begins inside `analyze_video` and ends after all frames are
processed and the encoded MP4 passes timing/frame-count validation. It does not
include HTTP upload validation, queue wait, or final database result publication.
The worker's first-run model initialization falls inside this timer. Source and
result evidence are in the locally generated `artifacts/stack/summary.json` and
`artifacts/stack/verification.json`; the artifacts directory is excluded from
source control. From the repository root, after `uv sync --frozen` and downloading
the licensed fixture, reproduce the isolated stack run with:

```sh
uv run python scripts/verify_stack.py --prepare
docker compose --env-file artifacts/stack/verify.env -f compose.yaml -f artifacts/stack/override.yaml -p trafficvision-verification up --build -d
uv run python scripts/verify_stack.py --timeout 1800
```

The private credentials stay under `artifacts/stack`. A fresh named Compose
project and model volume may take longer because it must download the checkpoint.

## Production browser functional smoke run (2026-10-01)

A real Edge browser used the production frontend to upload an 8.033-second H.264
excerpt of the same licensed video, draw a four-vertex ROI and one bidirectional
counting line, submit the job, play the annotated result, download both exports,
and inspect History at desktop and mobile widths. The result retained 241 frames
at 640x480 and produced 8 crossing events. The exported JSON agreed with the
displayed count. Browser playback reported an 8.033256-second video; no page
errors or horizontal overflow were observed. Local evidence is in
`artifacts/browser/verification.json` and screenshots under `artifacts/browser/`.

This separate CPU worker run measured 238.135419 processing seconds and
1.012029 frames/second; detection and tracking took 229.319772 seconds. The
short H.264 excerpt, ROI, line placement, host load and first-run timing differ
from the full-source runs above. The three throughput figures are individual
observations, not a controlled comparison or an accuracy result.

Observed software failure cases corrected during testing: Ogg/Theora streams
without average-rate metadata now use valid alternate stream rate metadata; final
progress callback errors cannot publish a result before pipeline success. Model
failure cases still need reviewed annotations: small distant vehicles, occlusion,
ambiguous vehicle class boundaries and identity changes. No baseline-versus-fine-tuned
accuracy comparison exists yet because no training experiment has been run.

## Prepare the evaluation set

Follow [ANNOTATION.md](ANNOTATION.md). Freeze source videos, split assignments,
annotations and configuration before evaluating. Include bright, low-light,
occluded, sparse and dense traffic when licensed examples are available. Record
missing conditions explicitly. Split by complete video; prefer disjoint camera
locations when assessing generalization. Never randomly split adjacent frames
across training and evaluation. Select parameters with validation data and reserve
test videos for the final comparison.

Install the locked environment using the [README](../README.md). Commands below
run from the repository root. The example paths identify data the user must prepare;
the repository does not claim these annotations or checkpoints already exist.

## Counting absolute error and MAE

The evaluator compares event counts, with exact labels and directions. It does
not pair events by timestamp or calculate event precision/recall. Store the
ground truth in `data/evaluation/ground_truth.json`, using this shape:

```json
{
  "schema_version": 1,
  "classes": ["car", "motorcycle", "bus", "truck"],
  "videos": [
    {
      "video_id": "camera_a_day_001",
      "line_ids": ["main"],
      "events": [
        {"class_name": "car", "line_id": "main", "direction": "A_to_B", "timestamp_video": 2.4}
      ]
    },
    {"video_id": "camera_b_empty_001", "line_ids": ["main"], "events": []}
  ]
}
```

The numbers above illustrate the file format and are not measured traffic data.
Each video needs an entry even when it contains zero crossings. Keep review notes,
license information and the exact ROI/line geometry in the separate dataset
manifest. Run each video with the same declared classes and its reviewed geometry.
The evaluator checks class and line IDs; reviewers must also verify source identity,
line coordinates, ROI, coverage interval and annotation policy against that manifest.

Create `data/evaluation/predictions.json` pointing to the exported `result.json`
from each successful run; paths are relative to this manifest:

```json
{
  "schema_version": 1,
  "videos": [
    {"video_id": "camera_a_day_001", "result": "../results/camera_a_day_001/result.json"},
    {"video_id": "camera_b_empty_001", "result": "../results/camera_b_empty_001/result.json"}
  ]
}
```

```sh
uv run python scripts/evaluate_counts.py --ground-truth data/evaluation/ground_truth.json --predictions data/evaluation/predictions.json --output data/evaluation/baseline-counting.json --by-line
```

The command refuses existing report files, missing/extra video predictions,
duplicate video IDs, repeated result-file paths, incompatible class/line scopes,
duplicate track/line/direction events, and counts inconsistent with their events.
`summary.json` is insufficient because event consistency cannot be checked.
Reports retain input file paths and SHA-256 hashes.

For video `v`, class `c`, direction `d`, let `G[v,c,d]` and `P[v,c,d]` be the
ground-truth and predicted counts summed across its declared lines.

| Report field | Definition |
| --- | --- |
| `cells[].absolute_error` | `abs(P[v,c,d] - G[v,c,d])`; includes every zero-count cell |
| `per_video[].absolute_error` | Absolute error of that video's total across classes/directions |
| `per_video[].mae_class_direction` | Mean cell error within that video |
| `mae_video_total` | Mean absolute total-count error over all declared videos |
| `mae_video_class_direction` | Mean cell error over all videos, selected classes and both directions |
| `per_class[].mae` | For each class, mean video error after summing both directions |
| `per_direction[].mae` | For each direction, mean video error after summing selected classes |
| `per_class_direction[].mae` | For each class/direction, mean absolute error over all videos |
| `per_line_class_direction[].mae` | Optional mean over videos declaring that line ID; denominator is reported |

Aggregate before taking absolute error for each named aggregate. Report both total
and cell metrics: confusing a car in one direction with a truck in the opposite
direction can produce zero total error while both class/direction predictions are
wrong. Long and short videos have equal weight in video MAE; this is not a percentage
or an event-weighted score. Do not average per-line errors across unrelated line IDs.

## Detection precision, recall and mAP

Prepare local YOLO box labels and copy
[`configs/dataset.example.yaml`](../configs/dataset.example.yaml) to a local dataset
configuration. The example intentionally retains all 80 COCO class names and
indices, so vehicle labels use **2, 3, 5, 7**. It can evaluate the unchanged baseline
and a fine-tuned model with that same vocabulary.

```sh
uv run python scripts/evaluate_detection.py --data configs/dataset.yaml --dataset-manifest data/dataset/manifest.csv --checkpoint data/models/yolo11n.pt --split test --device cpu --image-size 640 --batch 1 --seed 42 --output data/experiments/baseline-detection
```

The script requires a trusted local checkpoint, snapshots resolved local dataset
paths, disables dataset auto-downloads, and saves `evaluation.json` plus native
Ultralytics validation plots. Dataset and model class dictionaries must match
exactly. `--classes` selects labels; it does **not** remap a four-class dataset's
IDs 0..3 to a COCO model's IDs. Explicitly convert labels and the dataset vocabulary
when comparing models with different class heads, and preserve that conversion
as a versioned artifact.

The report contains precision, recall, mAP50 and mAP50-95 plus per-class metrics.
Ultralytics precision/recall use the maximum-F1 operating point on its confidence
sweep. The default candidate threshold `0.001` is appropriate for the sweep and
is separate from the dashboard's operating threshold. `--nms-iou` controls NMS,
not the IoU thresholds averaged in mAP. Classes without ground-truth instances
have null metrics and are excluded from the upstream macro average; a split with
no selected ground-truth instances is rejected. The report includes class support,
package/hardware metadata, checkpoint and manifest hashes, selected split, seed,
inference size, batch size and timing. Definitions follow the
[Ultralytics validation API](https://docs.ultralytics.com/modes/val/) and
[pinned metric implementation](https://github.com/ultralytics/ultralytics/blob/v8.3.203/ultralytics/utils/metrics.py).

The split/provenance manifest is hashed for traceability, not automatically audited
for licenses or leakage. Review and retain the dataset content hashes in it.

## Fine-tuning

Training has not been run. Complete licensing, annotation review, split isolation,
storage capacity and compute budgeting first. The readiness flag is a script
safeguard, not an interactive approval request.

```sh
uv run python scripts/train.py --data configs/dataset.yaml --dataset-manifest data/dataset/manifest.csv --checkpoint data/models/yolo11n.pt --output data/experiments/finetune-seed42 --device cpu --epochs 50 --batch 4 --image-size 640 --seed 42 --confirm-data-ready
```

The command refuses an existing output directory. It uses AdamW with an explicit
learning rate, deterministic algorithms, one data-loader process, no AMP and no
image cache by default. The experiment records input hashes, configuration,
versions, hardware, elapsed time, failure status if an exception occurs, and final
`best.pt`/`last.pt` hashes. Native `training/args.yaml`, `results.csv`, plots and
checkpoints retain the detailed training settings and trajectory. Review
[Ultralytics training arguments](https://docs.ultralytics.com/modes/train/).

Re-run with a new directory for each seed/configuration; deterministic settings
do not guarantee identical floating-point results across different hardware or
package versions. Use a compatible CUDA environment before specifying a GPU;
the default lock installs CPU PyTorch. Retaining an 80-class head while annotating
only vehicles does not establish performance on unannotated COCO classes. Make
no such claim. Compare baseline and fine-tuned checkpoints on the same held-out
videos, selected labels, ROI/lines and operating settings.

## Tracking and runtime

**IDF1 and HOTA are pending.** They require per-frame boxes with stable ground-truth
object identities, ignore/visibility rules, and matching predicted trajectories.
Crossing event IDs alone are not track ground truth. The MVP does not export full
per-frame tracking trajectories or run TrackEval. Add a reviewed trajectory export
and an appropriate [TrackEval](https://github.com/JonathonLuiten/TrackEval) dataset
adapter before reporting these metrics; do not derive them from count agreement.

For end-to-end runtime use the run's `processing_seconds`, `processed_frames`,
`inference_seconds` and `throughput_fps`, preserving hardware, checkpoint, device,
source resolution, source duration, inference size, classes and tracker settings.
Processing time includes decode, tracking, drawing, encoding and output validation;
it excludes API queue wait. `inference_seconds` combines detection and tracking.
`1000 * processing_seconds / processed_frames` is mean processing milliseconds
per frame, **not** p95 latency or live capture latency. Detection validation's
per-image timings cover a different workload and must be labeled separately.

Repeat several complete runs after a warm-up run when benchmarking steady-state
performance; separately report cold-start behavior if model loading is included.
Retain individual runs and report the aggregation used. Do not infer real-time
capability from one short clip or copy upstream GPU speed into a CPU report.

## Experiment and failure-case ledger

No baseline/improvement accuracy comparison is available until the labeled
experiments run. Use the following columns in the actual report:

| Experiment | Dataset/split hash | Checkpoint hash | Seed/config | P/R/mAP | Video/cell counting MAE | Runtime/hardware | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pretrained baseline | Pending | Pending | Pending | Not measured | Not measured | See executed smoke evidence in PROGRESS.md | Pending labeled evaluation |
| Fine-tuned candidate | Pending | Pending | Pending | Not measured | Not measured | Not run | Pending data and compute |

For each observed failure, record video ID, source timestamp, lighting, density,
occlusion, expected versus actual behavior, evidence frame/clip and proposed fix.
Separate detection misses, class confusion, ID switches, ROI/line mistakes and
timing errors. Re-evaluate fixes on validation, then freeze them before test.
Label anticipated failure cases as hypotheses until inspected examples exist.
