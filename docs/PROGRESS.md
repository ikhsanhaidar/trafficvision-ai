# Implementation progress

## Scope and assumptions

- User brief: upload-first MVP, milestones 1–4 in order; English product/documentation, Indonesian progress updates.
- 2026-09-30: workspace was empty; no existing changes or AGENTS.md found.
- Host initially: Windows, Python 3.10.0, Node 24.21.0, uv and Docker CLI present. Git and standalone FFmpeg absent from PATH. Docker Desktop was stopped; it has since been started successfully. uv selected installed Python 3.12.13 for the local environment.
- Default CPU, one worker process. YOLO11n COCO pretrained baseline, explicit ByteTrack adapter. No training or accuracy claims without labeled data.
- PyAV supplies FFmpeg video decoding/encoding and preserves source presentation timestamps. OpenCV supplies overlays/geometry. Audio is omitted from annotated analytical output and documented.
- PostgreSQL/Redis are the production services; SQLite and injected detector/task dispatch are test-only substitutes.
- Webcam, RTSP, multiple cameras and calibrated speed estimation are roadmap scope.

## Milestone 1 — verified

Architecture: validated normalized configuration → streamed PyAV frames → cached YOLO detector → per-run ByteTrack → bottom-center crossing counter → timestamped H.264 video and JSON/CSV, published as one result directory.

Implemented: separate detector/tracker/counter/video modules; metadata-mapped classes; model cache with per-run device switching; full-stream validation; finite-segment crossings with hysteresis, minimum age, class stabilization and per-direction deduplication; source PTS and VFR-preserving H.264; streaming JSONL/CSV and full JSON export; cancellation cleanup and atomic output-directory rename.

Executed locally on 2026-09-30:

- `uv lock` and `uv sync --frozen`: completed. Redis client changed to 5.2.1 to satisfy pinned Celery/Kombu; CPU torch 2.8.0+cpu and torchvision 0.23.0+cpu installed. Native dependency download took about 42 minutes on this connection.
- Counting-only suite: 30 passed.
- `pytest tests/test_counting.py tests/test_pipeline.py tests/test_evaluation.py -q`: 67 passed in 4.15 seconds, including actual encoded synthetic CFR/VFR fixtures, source timestamp offset, cancellation and encoder failure cleanup.
- Fixed final progress-callback ordering so an exception cannot leave a published result while reporting pipeline failure; regression passes.
- Downloaded and checksum-verified real CC BY 3.0 footage (Tomasz Sienicki, Gothenburg). Inspected first frame: stationary elevated road view. First smoke attempt exposed missing average_rate in Ogg/Theora; decoder now uses base_rate/guessed_rate when needed.
- Real model smoke **passed**: `python scripts/smoke_real_video.py --output artifacts/real-video-smoke`. 1,038 frames, 640×480, 34.599654 source seconds; output frame count/duration and event uniqueness/export consistency verified. CPU inference at image_size 640, confidence 0.25, default horizontal line: 27 crossings (26 car, 1 truck), 87.123789 processing seconds, 11.914082 FPS. These are observed outputs and execution throughput, **not accuracy metrics**. Metadata records Windows 11, 12 logical CPUs, PyTorch 2.8.0+cpu, Ultralytics 8.3.203, runtime torch_threads=8, checkpoint SHA-256 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`.
- The smoke script loads the model and validates input before the measured pipeline call; its reported processing duration excludes checkpoint download/model initialization and initial upload-style validation. Encoding and output validation are included. Worker runs may include first-use model load in processing time.

## Milestone 2 — verified on API and worker stack

FastAPI, Argon2/JWT cookie authentication, private UUID storage, PostgreSQL models/Alembic, durable queued rows, attempt fencing, Celery analysis/maintenance queues, cancellation, heartbeats and stale-job recovery are implemented. Dedicated recovery worker prevents long inference from starving recovery.

- Local full Python suite on 2026-10-01: **93 passed**, one dependency deprecation warning. Tests cover authentication, cross-origin protection, streamed upload limits, video validation, cancel/retry, duplicate task delivery, attempt fencing, failed encoding cleanup, DB commit uncertainty and stale result reaping. Tests use SQLite and injected synthetic inference for speed and exact failure control.
- Real PostgreSQL 16.10: **26 API/job tests passed** in generated per-test schemas; isolated Alembic upgrade and autogenerate drift check passed. Public production schema was not altered by these tests.
- Real Docker Compose stack (PostgreSQL 16.10, Redis 7.2.11, Celery analysis worker, separate maintenance worker and beat, FastAPI and Nginx): `/api/health/ready` passed. Authenticated API upload of the licensed 34.599654-second clip, preview, queueing, YOLO11n/ByteTrack analysis, results/events/exports and HTTP Range MP4 passed. JSON event count, summary count and paginated event total matched. Protected video/export endpoints returned 401 after logout.
- Docker run yielded 1,038 frames and 27 crossing events, processing time **346.717248 seconds**, throughput **2.993794 FPS** on CPU under Docker Desktop/WSL2. This one first-worker run includes the checkpoint download/model setup in measured processing time; it is not directly comparable to the native pipeline's 87.123789 seconds, which excluded model loading. Both runs use checkpoint SHA-256 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`. No labeled ground truth is available for accuracy/MAE.
- Commit-uncertainty upload regression was found and fixed. If the DB accepted a video row but its response was lost, cleanup now retains the referenced source/preview; failed commits still remove their files.
- Cancellation/recovery have passed controlled tests, not a hard-kill production drill.

## Milestone 3 — verified through the production browser and worker

React/TypeScript/Vite/Tailwind/Recharts Overview, New Analysis, Job Detail, History and Settings pages are complete, including normalized SVG ROI/line editor, polling, protected downloads, responsive layout and empty/loading/error/success states. Demo data is explicitly labeled and isolated from real run statistics. `npm run build`, `npm run lint`, `npm run format:check` and **9 Playwright tests passed**. Mock API browser tests cover upload limits, geometry, job actions and exports.

- Production Edge browser smoke on 2026-10-01 **passed**: uploaded a licensed 8.033-second H.264 excerpt (241 frames, 640×480), drew a four-vertex ROI and a bidirectional line, started the actual Celery/YOLO11n job, played the annotated result, downloaded JSON and CSV, and opened History. The exported JSON agreed with the 8 displayed crossing events; output video duration was 8.033256 seconds. No browser page errors or mobile horizontal overflow occurred. Desktop Job Detail and settled mobile History screenshots were inspected; evidence is under ignored `artifacts/browser/`.
- This separate Docker CPU run measured **238.135419 processing seconds / 1.012029 FPS**; its short input and execution conditions differ from the full-video run, so these figures are observations rather than a controlled performance comparison or accuracy measurement.
- Nginx initially returned 502 after the API container's IP changed during a rebuild. The proxy now re-resolves the Docker service address. In a deliberate replacement test, API IP changed from `172.20.0.4` to `172.20.0.9` while the frontend stayed running; proxied readiness returned 200.

## Milestone 4 — MVP deliverables verified; labeled evaluation pending

CPU Compose services and backend/frontend images built successfully, including the final proxy and backend fixes. A separate optional hash-pinned CUDA 12.8 lock, CI, README, API/model/license/annotation/evaluation/demo documentation and evaluation/fine-tuning scripts are present. `ruff check` and `ruff format --check` pass. Counting evaluation tests pass. The application met the MVP upload → draw → analyze → play → export criterion in a real browser. A real labeled evaluation set and fine-tuning training run remain unavailable, so no precision/recall/mAP, counting MAE, IDF1/HOTA or improvement claims are made. Optional CUDA execution remains untested: no verified GPU is available.

## Follow-up: counting-line guidance (2026-10-01)

A user uploaded a 12.1-second, 3840×2160 MP4 but could not select **Start analysis**. The live API logged successful upload (`201`) and preview (`200`), with no job creation request. The button correctly required a completed counting line; its instructions were below the large preview and easy to miss. New Analysis now displays the two-click instruction immediately above the preview, reports the first-point and completed-line states, and explains the disabled button. The browser workflow test verifies disabled → first point → enabled after second point. All 9 Playwright tests, frontend lint/format checks and production build passed. The updated frontend was deployed to the user's running localhost:8080 stack without recreating backend or database; proxied readiness returned 200.

## GitHub publication (2026-10-01)

Published the public repository [ikhsanhaidar/trafficvision-ai](https://github.com/ikhsanhaidar/trafficvision-ai) with `main` as the default branch. Initial commit `7b6b6d4` contains 82 source, configuration, test and documentation files (about 1.1 MB). Git ignore rules exclude local credentials, uploads, model weights, generated results, dependency environments and build output. An index scan found no local credential values or recognizable token/private-key patterns. README includes clone/setup instructions and a CI badge; CI runs frontend lint and formatting in addition to build/browser tests.

Pre-push checks passed: 93 Python tests, Ruff lint/format, TypeScript, Prettier and all 9 Playwright tests. The first [GitHub Actions run](https://github.com/ikhsanhaidar/trafficvision-ai/actions/runs/36870088651) passed both backend and frontend jobs on fresh hosted Linux runners. Local and remote initial commit hashes matched. The optional real-video workflow remained opt-in; its separate local functional results are recorded above.

### Resume notes

Long-running processes and partial agent changes may survive usage interruptions. Preserve existing files; inspect before resuming. Do not confuse implementation, synthetic verification, real-video functional smoke and model accuracy measurements. Verification-only secrets stay in ignored `artifacts/stack`, never in committed examples or output logs.
