# Sources, dependency choices and licenses

Sources were checked during implementation on 2026-09-30. This records upstream
provenance and engineering choices, not a legal conclusion or a claim that all
listed integrations have passed runtime tests. Exact dependency resolution lives
in the manifests/lockfiles; runtime verification belongs in `PROGRESS.md` and the
evaluation report. Retain upstream copyright and license files when distributing
dependencies or container images.

## Compatibility decisions

| Selection | Reason and primary reference |
| --- | --- |
| Python `>=3.10,<3.13` | Conservative shared project target for available binary wheels; Python 3.12 is the container target. |
| PyTorch `2.8.0`, torchvision `0.23.0` | The official [previous-version installation matrix](https://pytorch.org/get-started/previous-versions/#v280) pairs these versions and documents CPU wheels for Windows/Linux plus CUDA wheel indexes. The default lock uses the CPU index. A CUDA device requires a compatible CUDA build and driver, not merely a device-string change. |
| Ultralytics `8.3.203`, YOLO11n | Fixed baseline with YOLO11 and ByteTrack; [tagged package requirements](https://github.com/ultralytics/ultralytics/blob/v8.3.203/pyproject.toml) accept the selected torch/torchvision/OpenCV versions. Current online examples can refer to newer defaults, so the pinned implementation is authoritative. |
| OpenCV `4.12.0.88`, NumPy `2.2.6` | Explicit compatible NumPy major family for these wheels; [OpenCV Python package](https://pypi.org/project/opencv-python/4.12.0.88/) describes wheel installation and bundled libraries. Install only one OpenCV wheel flavor per environment. |
| PyAV `16.0.1` | Frame timestamps and encoding through FFmpeg. [Time-base documentation](https://pyav.org/docs/stable/api/time.html) explains `pts` and `time_base`; inspect the installed version when using examples from the rolling docs. |
| FastAPI `0.117.1`, Pydantic `2.11.9`, SQLAlchemy `2.0.43`, Alembic `1.16.5` | Pydantic v2 schemas and SQLAlchemy v2 sessions; consult [FastAPI security](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/), [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/), [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html), and [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html). |
| Celery `5.5.3`, redis-py `5.2.1`, psycopg `3.2.10` | Background execution and PostgreSQL transactions; redis-py 5.2.1 satisfies Celery/Kombu's Redis extra constraint. [Celery tasks](https://docs.celeryq.dev/en/v5.5.3/userguide/tasks.html) documents acknowledgement/retry behavior. A task can execute more than once, so database run ownership and atomic publication are application responsibilities. |

Pins are a reproducible baseline, not a statement that these are the newest
releases. Resolve and test dependency updates deliberately. Platform-specific
wheels and CUDA compatibility still require testing on the deployment machine.

## Model, tracker and data

| Artifact | Origin and license |
| --- | --- |
| YOLO11n checkpoint and Ultralytics package | [Model documentation](https://docs.ultralytics.com/models/yolo11/), [v8.3.203 license](https://github.com/ultralytics/ultralytics/blob/v8.3.203/LICENSE), [publisher licensing page](https://www.ultralytics.com/license): AGPL-3.0 by default; an Enterprise option is offered separately. This project's manifest selects `AGPL-3.0-only`; do not describe the combined application as MIT licensed. |
| ByteTrack algorithm | [Original paper](https://arxiv.org/abs/2110.06864) and [original repository license](https://github.com/FoundationVision/ByteTrack/blob/main/LICENSE) (MIT). This project uses the implementation shipped inside Ultralytics, whose own license still applies. |
| COCO pretraining data | [COCO terms](https://cocodataset.org/#termsofuse): annotations and underlying images have distinct terms; images retain their respective owners' rights. No COCO images or annotations are bundled here. The pretrained class order is in [the pinned COCO YAML](https://github.com/ultralytics/ultralytics/blob/v8.3.203/ultralytics/cfg/datasets/coco.yaml). |
| Smoke video | [Changing lanes in Gothenburg ubt.ogv](https://commons.wikimedia.org/wiki/File:Changing_lanes_in_Gothenburg_ubt.ogv), © 2009 Tomasz Sienicki (Tsca), recording dated 2009-07-25. Select the author's offered [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) license. Credit the author, link the source/license, and describe modifications when sharing annotated output. |

Run `python scripts/fetch_smoke_video.py` to fetch the original 9,785,538-byte
traffic video to `data/smoke/gothenburg.ogv`. The script verifies SHA-256
`55186644070ef8685332660374104acfa678ef258e9833c0f3920905bd68c919`, limits download
size, and writes a source manifest. The video is real footage, not synthetic.
It supplies no ground truth and is a functional smoke fixture, not an evaluation
dataset. Keep generated video out of version control and retain the `.source.json`
attribution alongside any shared derivative. An annotated result changes the
original by adding boxes, IDs, lines and counts; identify that change explicitly.

## Component license references

| Component | Upstream license/reference |
| --- | --- |
| Python | [PSF license](https://docs.python.org/3/license.html) |
| PyTorch / torchvision | [PyTorch BSD-style license and third-party notices](https://github.com/pytorch/pytorch/blob/v2.8.0/LICENSE); [torchvision BSD-3-Clause](https://github.com/pytorch/vision/blob/v0.23.0/LICENSE) |
| NumPy | [BSD-3-Clause and bundled notices](https://github.com/numpy/numpy/blob/v2.2.6/LICENSE.txt) |
| OpenCV / opencv-python | [OpenCV Apache-2.0](https://github.com/opencv/opencv/blob/4.12.0/LICENSE); Python packaging scripts use MIT and binary wheels include [third-party components](https://github.com/opencv/opencv-python/blob/4.x/LICENSE-3RD-PARTY.txt). |
| PyAV / FFmpeg | [PyAV BSD-3-Clause](https://github.com/PyAV-Org/PyAV/blob/v16.0.1/LICENSE.txt); [FFmpeg licensing](https://ffmpeg.org/legal.html) depends on build options and included libraries (LGPL/GPL). A Python wrapper license does not replace codec/binary obligations. |
| LAP solver | [lap BSD-2-Clause](https://github.com/gatagat/lap/blob/master/LICENSE) |
| FastAPI / Pydantic / pydantic-settings | [FastAPI MIT](https://github.com/fastapi/fastapi/blob/0.117.1/LICENSE), [Pydantic MIT](https://github.com/pydantic/pydantic/blob/v2.11.9/LICENSE), [pydantic-settings MIT](https://github.com/pydantic/pydantic-settings/blob/v2.10.1/LICENSE) |
| Uvicorn | [BSD-3-Clause](https://github.com/encode/uvicorn/blob/0.37.0/LICENSE.md) |
| SQLAlchemy / Alembic | [SQLAlchemy MIT](https://github.com/sqlalchemy/sqlalchemy/blob/rel_2_0_43/LICENSE), [Alembic MIT](https://github.com/sqlalchemy/alembic/blob/rel_1_16_5/LICENSE) |
| PostgreSQL / psycopg | [PostgreSQL License](https://www.postgresql.org/about/licence/); [psycopg LGPL-3.0](https://github.com/psycopg/psycopg/blob/3.2.10/LICENSE.txt), with separate binary-library notices. |
| Celery | [BSD-3-Clause](https://github.com/celery/celery/blob/v5.5.3/LICENSE) |
| Redis / redis-py | [Official license matrix](https://redis.io/legal/licenses/): server 7.2 and earlier BSD-3-Clause; 7.4 RSALv2/SSPLv1; 8+ additionally offers AGPLv3. The Python client is MIT. Check the actual container tag; client and server versions/licenses are distinct. |
| python-multipart / pwdlib / PyJWT | [python-multipart Apache-2.0](https://github.com/Kludex/python-multipart/blob/master/LICENSE.txt), [pwdlib MIT](https://github.com/frankie567/pwdlib/blob/main/LICENSE), [PyJWT MIT](https://github.com/jpadilla/pyjwt/blob/2.10.1/LICENSE) |
| React / Vite / Tailwind CSS / Recharts | [React MIT](https://github.com/facebook/react/blob/main/LICENSE), [Vite MIT](https://github.com/vitejs/vite/blob/main/LICENSE), [Tailwind MIT](https://github.com/tailwindlabs/tailwindcss/blob/main/LICENSE), [Recharts MIT](https://github.com/recharts/recharts/blob/main/LICENSE) |
| TypeScript | [Apache-2.0](https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt) |

This is an inventory of direct components and notable binary dependencies, not a
complete software bill of materials. Consult installed distributions and image
contents for transitive notices before redistribution. Docker Engine/Compose and
Docker Desktop are different products; [Docker Desktop subscription terms](https://www.docker.com/legal/docker-subscription-service-agreement/)
apply independently of this application's source license.
