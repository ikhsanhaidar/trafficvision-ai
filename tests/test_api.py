"""Authenticated upload-to-export integration with real synthetic media and fake detections."""

import csv
import io
import os
import time
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import anyio
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema
from starlette import formparsers
from trafficvision.api import create_app
from trafficvision.auth import COOKIE_NAME, LoginLimiter
from trafficvision.db import Database, Video
from trafficvision.jobs import run_job
from trafficvision.pipeline import analyze_video
from trafficvision.settings import Settings

TEST_PASSWORD = "synthetic-test-password"
TEST_PASSWORD_HASH = PasswordHash.recommended().hash(TEST_PASSWORD)


def configuration():
    return {
        "classes": ["car"],
        "min_track_age": 2,
        "hysteresis": 0.005,
        "lines": [{"id": "main", "start": {"x": 0.1, "y": 0.5}, "end": {"x": 0.9, "y": 0.5}}],
    }


def pipeline_analyzer(*args, **kwargs):
    from test_pipeline import SyntheticDetector, SyntheticTrackerFactory

    return analyze_video(
        *args, **kwargs, detector=SyntheticDetector(), tracker_factory=SyntheticTrackerFactory()
    )


@pytest.fixture
def service(tmp_path, request):
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    if external_url := os.environ.get("TV_TEST_DATABASE_URL"):
        url = make_url(external_url)
        if url.get_backend_name() != "postgresql":
            raise ValueError("TV_TEST_DATABASE_URL must name a PostgreSQL test database.")
        # Each test owns only its generated schema, never the deployment's public tables.
        schema = f"test_{uuid.uuid4().hex}"
        admin = create_engine(url)
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))

        def cleanup_schema():
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
            admin.dispose()

        request.addfinalizer(cleanup_schema)
        database_url = url.update_query_dict(
            {"options": f"-csearch_path={schema}"}
        ).render_as_string(hide_password=False)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        storage_root=tmp_path / "private",
        secret_key="test-secret-" * 5,
        admin_password_hash=TEST_PASSWORD_HASH,
        allowed_origins=["http://testserver"],
        lease_seconds=5,
        max_job_seconds=30,
        dispatch_retry_seconds=1,
    )
    database = Database(settings.database_url)
    database.create_schema()
    deliveries = []
    app = create_app(
        settings,
        database=database,
        dispatcher=lambda job_id, attempt: deliveries.append((job_id, attempt)),
    )
    with TestClient(app, headers={"Origin": "http://testserver"}) as client:
        login = client.post(
            "/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD}
        )
        assert login.status_code == 200
        yield SimpleNamespace(
            settings=settings, database=database, app=app, client=client, deliveries=deliveries
        )


def upload(service, clip):
    response = service.client.post(
        "/api/videos", files={"file": ("../../camera.mp4", clip.path.read_bytes(), "video/mp4")}
    )
    assert response.status_code == 201, response.text
    return response.json()


def start(service, video):
    response = service.client.post(
        "/api/jobs", json={"video_id": video["id"], "configuration": configuration()}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_analysis_exports_and_private_range_download(service, synthetic_video):
    video = upload(service, synthetic_video())
    assert video["filename"] == "camera.mp4"
    assert video["info"]["frame_count"] == 6
    preview = service.client.get(f"/api/videos/{video['id']}/preview")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"
    job = start(service, video)
    assert job["status"] == "queued" and service.deliveries == [(job["id"], 1)]
    assert service.client.get(f"/api/jobs/{job['id']}/result").status_code == 409
    assert run_job(service.database, service.settings, job["id"], 1, analyzer=pipeline_analyzer)
    assert not run_job(service.database, service.settings, job["id"], 1, analyzer=pipeline_analyzer)
    detail = service.client.get(f"/api/jobs/{job['id']}").json()
    assert detail["status"] == "succeeded" and detail["progress"] == 1
    assert detail["processing_seconds"] > 0 and detail["throughput_fps"] > 0
    assert detail["summary"]["crossing_total"] == 2
    first = service.client.get(f"/api/jobs/{job['id']}/events?limit=1").json()
    second = service.client.get(f"/api/jobs/{job['id']}/events?limit=1&offset=1").json()
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["direction"] == "A_to_B"
    assert second["items"][0]["direction"] == "B_to_A"
    export = service.client.get(f"/api/jobs/{job['id']}/export?format=json")
    assert len(export.json()["events"]) == 2
    assert export.json()["events"] == first["items"] + second["items"]
    exported_csv = service.client.get(f"/api/jobs/{job['id']}/export?format=csv")
    assert len(list(csv.DictReader(io.StringIO(exported_csv.text)))) == 2
    ranged = service.client.get(f"/api/jobs/{job['id']}/video", headers={"Range": "bytes=0-31"})
    assert ranged.status_code == 206 and len(ranged.content) == 32
    assert ranged.headers["accept-ranges"] == "bytes"
    assert ranged.headers["cache-control"] == "no-store"
    assert service.client.get("/api/jobs").json()["total"] == 1
    assert service.client.get("/api/jobs?limit=1&offset=1").json()["items"] == []
    service.client.cookies.clear()
    for path in [
        f"/api/videos/{video['id']}/preview",
        f"/api/jobs/{job['id']}/video",
        f"/api/jobs/{job['id']}/export",
        f"/api/jobs/{job['id']}/result",
        "/api/jobs",
    ]:
        assert service.client.get(path).status_code == 401


def test_auth_origin_expiration_and_logout(service):
    assert service.client.get("/api/auth/me").json() == {"username": "admin"}
    assert (
        service.client.post(
            "/api/auth/logout", headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert (
        service.client.post(
            "/api/auth/logout", headers={"Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 403
    )
    assert (
        service.client.get("/api/auth/me", headers={"Origin": "https://evil.invalid"}).status_code
        == 403
    )
    assert service.client.post("/api/auth/logout").status_code == 204
    assert service.client.get("/api/auth/me").status_code == 401


def test_cookie_write_requires_explicit_allowed_origin(service):
    del service.client.headers["Origin"]
    assert service.client.post("/api/auth/logout").status_code == 403
    assert service.client.get("/api/auth/me").status_code == 200


def test_docs_and_readiness_use_public_api_prefix(service, monkeypatch):
    from trafficvision import api

    monkeypatch.setattr(
        api.Redis,
        "from_url",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(ping=lambda: True)),
    )
    service.client.cookies.clear()
    assert service.client.get("/api/docs").status_code == 200
    assert service.client.get("/api/openapi.json").json()["info"]["title"] == "TrafficVision AI"
    assert service.client.get("/api/health/live").status_code == 200
    assert service.client.get("/api/health/ready").json()["status"] == "ready"
    assert service.client.get("/docs").status_code == 404


@pytest.mark.parametrize("authenticated", [False, True])
def test_streamed_size_limit_closes_spooled_multipart_before_upload(
    service, monkeypatch, authenticated
):
    service.settings.max_upload_bytes = 1024
    opened, received, sent = [], [], []
    spool = formparsers.SpooledTemporaryFile

    def track_spool(*args, **kwargs):
        file = spool(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", track_spool)
    chunks = iter(
        [
            b'--limit\r\nContent-Disposition: form-data; name="file"; filename="test.mp4"\r\n'
            b"Content-Type: video/mp4\r\n\r\n" + b"x" * 100,
            b"x" * (1024 * 1024 + 1024),
            b"\r\n--limit--\r\n",
        ]
    )
    headers = [
        (b"content-type", b"multipart/form-data; boundary=limit"),
        (b"origin", b"http://testserver"),
    ]
    if authenticated:
        headers.append(
            (b"cookie", f"{COOKIE_NAME}={service.client.cookies.get(COOKIE_NAME)}".encode())
        )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/videos",
        "raw_path": b"/api/videos",
        "query_string": b"",
        "scheme": "http",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "http_version": "1.1",
    }

    async def receive():
        body = next(chunks, b"")
        received.append(len(body))
        return {"type": "http.request", "body": body, "more_body": bool(body)}

    async def send(message):
        sent.append(message)

    anyio.run(service.app, scope, receive, send)
    assert next(
        message["status"] for message in sent if message["type"] == "http.response.start"
    ) == (413 if authenticated else 401)
    if authenticated:
        assert len(received) == 2 and opened and all(file.closed for file in opened)
    else:
        assert not received and not opened
    assert list((service.settings.storage_root / "videos").iterdir()) == []


def test_auth_credentials_and_expired_session(service):
    service.client.cookies.clear()
    wrong = service.client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert wrong.status_code == 401
    forbidden = service.client.post(
        "/api/auth/login",
        headers={"Origin": "https://evil.invalid"},
        json={"username": "admin", "password": TEST_PASSWORD},
    )
    assert forbidden.status_code == 403
    login = service.client.post(
        "/api/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "admin", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    service.client.cookies.clear()
    expired = jwt.encode(
        {
            "sub": "admin",
            "iat": time.time() - 100,
            "exp": time.time() - 1,
            "jti": "expired",
            "iss": "trafficvision",
            "aud": "trafficvision",
        },
        service.settings.secret_key,
        algorithm="HS256",
    )
    service.client.cookies.set(COOKIE_NAME, expired, path="/api")
    assert service.client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("content", [b"", b"not a video"])
def test_invalid_upload_is_rejected_and_removed(service, content):
    response = service.client.post("/api/videos", files={"file": ("bad.mp4", content, "video/mp4")})
    assert response.status_code == 422
    assert list((service.settings.storage_root / "videos").iterdir()) == []


def test_upload_preserves_files_when_commit_response_is_lost(service, synthetic_video):
    def commit_response_lost(session):
        raise ConnectionError("Synthetic response lost after upload commit")

    event.listen(service.database.session.class_, "after_commit", commit_response_lost)
    try:
        with pytest.raises(ConnectionError, match="response lost"):
            upload(service, synthetic_video())
    finally:
        event.remove(service.database.session.class_, "after_commit", commit_response_lost)

    with service.database.session() as session:
        video = session.scalar(select(Video))
        assert video is not None
        directory = service.settings.storage_root / "videos" / video.id
    assert (directory / "source").is_file()
    assert (directory / "preview.jpg").is_file()
    assert service.client.get(f"/api/videos/{video.id}/preview").status_code == 200


def test_upload_removes_files_when_commit_did_not_run(service, synthetic_video):
    def reject_commit(session):
        raise RuntimeError("Synthetic failure before upload commit")

    event.listen(service.database.session.class_, "before_commit", reject_commit)
    try:
        with pytest.raises(RuntimeError, match="before upload commit"):
            upload(service, synthetic_video())
    finally:
        event.remove(service.database.session.class_, "before_commit", reject_commit)

    with service.database.session() as session:
        assert session.scalar(select(Video)) is None
    assert list((service.settings.storage_root / "videos").iterdir()) == []


def test_size_limit_and_unauthenticated_upload_before_multipart_parse(service):
    service.settings.max_upload_bytes = 1024
    response = service.client.post("/api/videos", files={"file": ("oversized.mp4", b"x" * 2048)})
    assert response.status_code == 413
    assert list((service.settings.storage_root / "videos").iterdir()) == []
    service.client.cookies.clear()
    response = service.client.post(
        "/api/videos",
        content=b"malformed",
        headers={
            "Content-Type": "multipart/form-data; boundary=missing",
            "Content-Length": "999999999",
        },
    )
    assert response.status_code == 401


def test_deletion_requires_terminal_jobs_and_unreferenced_video(service, synthetic_video):
    video = upload(service, synthetic_video())
    job = start(service, video)
    assert service.client.delete(f"/api/videos/{video['id']}").status_code == 409
    assert service.client.delete(f"/api/jobs/{job['id']}").status_code == 409
    assert service.client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    assert service.client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert service.client.delete(f"/api/videos/{video['id']}").status_code == 204
    assert list((service.settings.storage_root / "videos").iterdir()) == []
    assert service.client.get(f"/api/jobs/{job['id']}").status_code == 404


def test_settings_geometry_gpu_and_limits(service, synthetic_video):
    settings = service.client.get("/api/settings").json()
    assert settings["devices"] == ["cpu"]
    assert settings["classes"] == ["car", "motorcycle", "bus", "truck"]
    video = upload(service, synthetic_video())
    config = configuration()
    config["device"] = "cuda:0"
    assert (
        service.client.post(
            "/api/jobs", json={"video_id": video["id"], "configuration": config}
        ).status_code
        == 422
    )
    config["device"] = "cpu"
    config["lines"][0]["start"]["x"] = 2
    assert (
        service.client.post(
            "/api/jobs", json={"video_id": video["id"], "configuration": config}
        ).status_code
        == 422
    )
    assert service.client.get("/api/jobs?limit=100000").status_code == 422
    assert service.client.get("/api/jobs/not-an-id").status_code == 404


def test_auth_configuration_fails_closed(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'empty.db'}",
        storage_root=tmp_path / "data",
        secret_key="",
        admin_password_hash="",
    )
    with pytest.raises(ValueError, match="TV_SECRET_KEY"):
        with TestClient(create_app(settings)):
            pass
    with pytest.raises(ValueError, match="explicit"):
        Settings(_env_file=None, allowed_origins=["*"])


def test_login_limit_uses_rolling_minute(monkeypatch):
    from trafficvision import auth

    now = [100.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    limiter = LoginLimiter()
    for _ in range(5):
        limiter.check("client")
    now[0] = 130.0
    for _ in range(5):
        limiter.check("client")
    with pytest.raises(HTTPException) as error:
        limiter.check("client")
    assert error.value.status_code == 429
    now[0] = 160.0
    limiter.check("client")
    assert len(limiter.attempts["client"]) == 6
