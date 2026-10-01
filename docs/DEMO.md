# Five-minute portfolio demo

Complete the [README setup](../README.md) before the interview. Start PostgreSQL,
Redis, API, worker and frontend; verify readiness, sign in, and download the model
once. Keep one previously completed real-video analysis available because CPU
processing time is hardware-dependent and can exceed the demo window. Label it
as a previous run; never simulate a finished analysis.

Fetch the licensed traffic fixture from the repository root:

```sh
uv run python scripts/fetch_smoke_video.py
```

This creates `data/smoke/gothenburg.ogv` and its source manifest after verifying the
pinned hash. Use the original file for upload. The backend creates a decoded preview
and H.264 annotated output; the browser does not need to play the original OGV.
The clip is real footage by Tomasz Sienicki, CC BY 3.0; preserve its attribution
from [SOURCES.md](SOURCES.md). No ground-truth accuracy claim is available for it.

| Time | Show | Explain |
| --- | --- | --- |
| 0:00-0:40 | Overview and History | Upload-first static-camera analysis; statistics come from completed jobs. Distinguish any explicitly labeled Demo content from actual runs. |
| 0:40-1:40 | New Analysis | Upload the fixture, review dimensions/duration, draw the road ROI and a finite directed counting line across the visible traffic lane. Select car, motorcycle, bus and truck, CPU, confidence 0.25 and inference size 640 (320 for a faster rehearsal). |
| 1:40-2:20 | Start analysis and Job Detail | Show queued/running state, progress and processing status. Describe the separate worker and one analysis process per CPU worker. |
| 2:20-3:20 | Completed real run | Play annotated video; identify bounding boxes, persistent track IDs, bottom-center points and the counting line. If the fresh job is still running, open the prepared previous run and say so. |
| 3:20-4:10 | Statistics and exports | Show crossings by class/direction and video-time intervals, source duration, processing duration and measured throughput. Open events and export JSON/CSV. |
| 4:10-5:00 | Configuration and engineering evidence | Show preserved ROI/settings/checkpoint metadata. Explain cancellation/retry, test evidence, evaluation protocol and the main failure modes. |

Select **Counting line**, then click its start and end points directly on the
video preview. The **Start analysis** button becomes available after the second
point; an ROI is optional. Draw the ROI around the road without self-intersections.
Place the line where
vehicles are visible before and after crossing, away from image edges and severe
occlusion. A left-to-right line has side A above and B below: movement downward
is `A_to_B`. Reversing the line reverses these labels. The line must intersect
actual trajectories; zero counts may be a legitimate result of placement or footage.

Use a separate short job to demonstrate cancel, then show its final canceled state.
Use retry only when a real failure exists and its cause has been addressed.
Discuss available failure/cancellation tests without manufacturing a production
failure. Verify actual tests in [PROGRESS.md](PROGRESS.md) before claiming they pass.

The pipeline can also be rehearsed independently of the web stack:

```sh
uv run trafficvision data/smoke/gothenburg.ogv --config examples/analysis.json --output data/results/demo-cli
```

The output directory must be new. The example line is a starting configuration,
not a reviewed annotation. Inspect the preview/footage and use the UI to choose
appropriate geometry for the actual demo.

Explain that counts represent track crossings, not guaranteed unique vehicles.
ID switches, occlusion, class confusion and repeated re-entry can change counts.
No speed measurement is provided without spatial/time calibration. The app
preserves source video timing in the annotated output and omits audio. Quote only
the throughput from the demonstrated run and its hardware/configuration. Detection
accuracy, counting MAE, IDF1 and HOTA remain pending until the necessary licensed
annotations and actual experiments are available; see [EVALUATION.md](EVALUATION.md).

Before sharing a recording, retain attribution for the source footage and describe
the added overlays. Keep credentials out of the capture. Explain that webcam,
RTSP and multiple cameras are future scope after the upload workflow is verified.
