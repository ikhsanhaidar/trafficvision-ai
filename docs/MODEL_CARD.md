# TrafficVision AI baseline model card

## Identity and intended use

The default detector is Ultralytics **YOLO11n detection**, checkpoint `yolo11n.pt`,
using `ultralytics==8.3.203` with PyTorch. This is a pretrained baseline, not a
TrafficVision-trained model. YOLO11 detection weights are pretrained on COCO's
80 classes. The small checkpoint is chosen for a resource-constrained portfolio
baseline; no speed or accuracy advantage has been measured for this application.
See the [official YOLO11 model documentation](https://docs.ultralytics.com/models/yolo11/).

The intended task is retrospective vehicle crossing analysis from a stationary
camera with a user-reviewed ROI and finite counting line. This model is not
validated for enforcement, safety-critical decisions, individual identification,
or vehicle speed estimation. Webcam, RTSP and multi-camera use are later work.

## Classes and checkpoint contract

| TrafficVision label | Expected YOLO11 COCO index |
| --- | --- |
| `car` | 2 |
| `motorcycle` | 3 |
| `bus` | 5 |
| `truck` | 7 |

These indices describe the supplied COCO checkpoint, **not a universal mapping**.
The adapter resolves requested labels from `model.names` at load time. A replacement
checkpoint must expose the requested names; missing classes must produce a useful
error, not a silently substituted index. The mapping is documented in
[Ultralytics' pinned COCO configuration](https://github.com/ultralytics/ultralytics/blob/v8.3.203/ultralytics/cfg/datasets/coco.yaml).
Vans, three-wheelers and local vehicle subclasses have no dedicated MVP label.

## Tracking and counting interpretation

ByteTrack associates detections over time; tracker state belongs to one run.
Counting uses each box's bottom-center point, line-side changes and intersection
with the finite line segment. Hysteresis and a minimum track age suppress some
jitter. A track may count at most once per line per direction in a run. Class
stabilization applies per track. See the pipeline configuration for actual settings.

The output measures **crossings**, not distinct physical vehicles. ID switches,
lost tracks, re-entry, class confusion or missed boxes can change counts. A large
confidence threshold can also remove the lower-confidence observations useful
to ByteTrack. Polygon/line placement and camera viewpoint are part of the model
system and must be evaluated together.

## Provenance and reproducibility

Each result should retain checkpoint identity and SHA-256, actual class mapping,
package versions, inference size, confidence threshold, device, tracker settings,
ROI/line coordinates, input-video timing and measured processing time. Hashes in a
run identify the actual file; a filename alone does not prove identical weights.
Load only checkpoint files from a trusted source. Downloading weights is an
explicit setup step or the documented behavior of the model loader.

The baseline is distributed under Ultralytics' AGPL-3.0 terms, with a separate
Enterprise option. COCO image rights remain those of the original image owners;
dataset and model rights are distinct. See [SOURCES.md](SOURCES.md) for primary
license references and the real smoke video's independent attribution.

## Evaluation status and limitations

No project-specific precision, recall, mAP, counting MAE, IDF1 or HOTA is claimed
by this card. A successful smoke run establishes execution and artifact creation;
it does not establish accuracy. Consult the evaluation report for measured runs
and their hardware/configuration rather than treating upstream benchmarks as local
results.

Expected failure cases include tiny distant vehicles, heavy occlusion, night or
rain, blur/compression, reflections, unusual vehicle types, camera shake and abrupt
lighting changes. These are hypotheses to inspect and label, not measured error
rates. Domain performance on Indonesian roads is unverified. Evaluate separately
by complete video/camera location, lighting, occlusion and density; do not split
adjacent frames across train and test. Fine-tuning and track metrics require the
corresponding licensed annotations before an experiment can be reported.
