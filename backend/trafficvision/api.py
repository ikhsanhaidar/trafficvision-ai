"""Authenticated API. Video files never enter a public static directory."""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from trafficvision.auth import COOKIE_NAME, LoginLimiter, authenticate, require_user, session_token
from trafficvision.db import Database, Event, Job, Video
from trafficvision.jobs import TERMINAL, dispatch_job
from trafficvision.schemas import AnalysisConfig, VideoInfo
from trafficvision.settings import Settings, get_settings
from trafficvision.storage import Storage, canonical_id, display_filename
from trafficvision.video_io import VideoError, VideoLimits, probe_video

logger = logging.getLogger("trafficvision.api")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: str
    configuration: AnalysisConfig


class VideoResponse(BaseModel):
    id: str
    filename: str
    info: VideoInfo
    created_at: str


class JobResponse(BaseModel):
    id: str
    video_id: str
    filename: str
    status: Literal["queued", "running", "succeeded", "failed", "canceled"]
    configuration: AnalysisConfig
    video: VideoInfo
    progress: float
    processed_frames: int
    processing_seconds: float | None
    throughput_fps: float | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    error: str | None
    attempt: int
    cancel_requested: bool
    summary: dict | None


class JobPage(BaseModel):
    items: list[JobResponse]
    total: int


def iso_time(value: float | None) -> str | None:
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def job_response(job: Job, video: Video) -> dict:
    return {
        "id": job.id,
        "video_id": video.id,
        "filename": video.filename,
        "status": job.status,
        "configuration": job.configuration,
        "video": video.info,
        "progress": job.progress,
        "processed_frames": job.processed_frames,
        "processing_seconds": job.processing_seconds,
        "throughput_fps": job.throughput_fps,
        "created_at": iso_time(job.created_at),
        "started_at": iso_time(job.started_at),
        "finished_at": iso_time(job.finished_at),
        "error": job.error,
        "attempt": job.attempt,
        "cancel_requested": job.cancel_requested,
        "summary": job.summary,
    }


def get_id(value: str) -> str:
    try:
        return canonical_id(value)
    except ValueError:
        raise HTTPException(404, "Item not found.") from None


def find_job(session, value: str) -> Job:
    job = session.get(Job, get_id(value))
    if job is None:
        raise HTTPException(404, "Analysis job not found.")
    return job


class RequestTooLarge(MultiPartException):
    """Let Starlette close partially spooled files before reporting a size error."""


class SecurityBoundary:
    """Explicit origin checks, bounded request streaming and private response caching."""

    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        unsafe = scope["method"] not in {"GET", "HEAD", "OPTIONS"}
        cookie = COOKIE_NAME in headers.get("cookie", "")
        origin = headers.get("origin")
        if (
            (origin is not None and origin not in self.settings.allowed_origins)
            or headers.get("sec-fetch-site") == "cross-site"
        ) and (unsafe or cookie):
            return await JSONResponse({"detail": "This request origin is not allowed."}, 403)(
                scope, receive, send
            )
        if unsafe and origin is None and (cookie or headers.get("sec-fetch-site")):
            return await JSONResponse({"detail": "An allowed Origin header is required."}, 403)(
                scope, receive, send
            )
        if scope["path"] == "/api/videos" and scope["method"] == "POST":
            # Authenticate before Starlette can spool the multipart body to disk.
            try:
                require_user(Request(scope))
            except HTTPException as exc:
                return await JSONResponse({"detail": exc.detail}, exc.status_code)(
                    scope, receive, send
                )
        maximum = (
            self.settings.max_upload_bytes + 1024 * 1024
            if scope["path"] == "/api/videos"
            else 65536
        )
        try:
            declared = int(headers.get("content-length", "0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid content length."}, 400)(
                scope, receive, send
            )
        if declared < 0:
            return await JSONResponse({"detail": "Invalid content length."}, 400)(
                scope, receive, send
            )
        if unsafe and declared > maximum:
            return await JSONResponse({"detail": "Request exceeds the upload size limit."}, 413)(
                scope, receive, send
            )
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if unsafe and received > maximum:
                    raise RequestTooLarge("Request exceeds the upload size limit.")
            return message

        async def private_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(message)

        await self.app(scope, bounded_receive, private_send)


def create_app(
    settings: Settings | None = None, *, database: Database | None = None, dispatcher=None
) -> FastAPI:
    settings = settings or get_settings()
    database = database or Database(settings.database_url)
    storage = Storage(settings.storage_root)
    limiter = LoginLimiter()

    @asynccontextmanager
    async def lifespan(app):
        settings.validate_security()
        storage.initialize()
        yield
        database.dispose()

    app = FastAPI(
        title="TrafficVision AI",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
        description="Private video analysis. Sign in first; authenticated downloads support HTTP Range.",
    )
    app.state.settings = settings
    app.state.database = database
    app.state.storage = storage
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Range"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )
    app.add_middleware(SecurityBoundary, settings=settings)

    @app.exception_handler(StarletteHTTPException)
    async def request_error(request, exc):
        # Request.form converts multipart failures to HTTP 400 after closing its files.
        # Preserve 413 for our streaming limit, including requests without Content-Length.
        if isinstance(exc.__cause__ or exc.__context__, RequestTooLarge):
            return JSONResponse({"detail": "Request exceeds the upload size limit."}, 413)
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestTooLarge)
    async def oversized_request(request, exc):
        return JSONResponse({"detail": "Request exceeds the upload size limit."}, 413)

    public = APIRouter(prefix="/api")
    private = APIRouter(prefix="/api", dependencies=[Depends(require_user)])

    @public.get("/health/live", tags=["Health"])
    def live():
        return {"status": "alive"}

    @public.get("/health/ready", tags=["Health"])
    def ready():
        checks = {"database": False, "redis": False}
        try:
            with database.session() as session:
                session.execute(select(Job.id).limit(1))
            checks["database"] = True
        except Exception:
            logger.warning("Database readiness check failed.")
        try:
            with Redis.from_url(
                settings.redis_url, socket_connect_timeout=2, socket_timeout=2
            ) as client:
                checks["redis"] = bool(client.ping())
        except Exception:
            logger.warning("Redis readiness check failed.")
        return JSONResponse(
            {"status": "ready" if all(checks.values()) else "unavailable", "checks": checks},
            status_code=200 if all(checks.values()) else 503,
        )

    @public.post("/auth/login", tags=["Authentication"])
    def login(body: LoginRequest, request: Request, response: Response):
        limiter.check(request.client.host if request.client else "unknown")
        if not authenticate(body.username, body.password, settings):
            raise HTTPException(401, "Invalid username or password.")
        response.set_cookie(
            COOKIE_NAME,
            session_token(settings),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            path="/api",
            max_age=settings.session_seconds,
        )
        return {"username": settings.admin_username}

    @private.get("/auth/me", tags=["Authentication"])
    def me():
        return {"username": settings.admin_username}

    @private.post("/auth/logout", status_code=204, tags=["Authentication"])
    def logout(response: Response):
        response.delete_cookie(
            COOKIE_NAME,
            path="/api",
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
        )

    @private.get("/settings", tags=["Configuration"])
    def capabilities():
        return {
            "limits": {
                "max_bytes": settings.max_upload_bytes,
                "max_duration_seconds": settings.max_video_seconds,
                "max_dimension": settings.max_video_dimension,
                "max_pixels": settings.max_video_pixels,
                "max_frames": settings.max_video_frames,
            },
            "classes": ["car", "motorcycle", "bus", "truck"],
            "checkpoint": os.path.basename(os.environ.get("MODEL_CHECKPOINT", "yolo11n.pt")),
            "devices": ["cpu", "cuda:0"] if settings.gpu_enabled else ["cpu"],
            "default_device": "cpu",
            "image_sizes": [320, 480, 640, 960, 1280],
        }

    @private.post("/videos", response_model=VideoResponse, status_code=201, tags=["Videos"])
    def upload_video(file: UploadFile = File(...)):
        video_id = str(uuid.uuid4())
        directory = storage.video_dir(video_id)
        directory.mkdir(parents=True, exist_ok=False)
        source, preview = directory / "source", directory / "preview.jpg"
        saved = False
        persistence_started = False
        try:
            size = 0
            with source.open("xb") as destination:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(413, "Video exceeds the upload size limit.")
                    destination.write(chunk)
            limits = VideoLimits(
                settings.max_upload_bytes,
                settings.max_video_seconds,
                settings.max_video_dimension,
                settings.max_video_pixels,
                settings.max_video_frames,
            )
            try:
                info = probe_video(source, preview, limits)
            except VideoError as exc:
                # Decoder messages can include private paths; retain only our known validations.
                message = str(exc)
                if "decod" in message.lower() or str(directory) in message:
                    message = (
                        "The file is not a supported, fully decodable video. Try an H.264 MP4 file."
                    )
                raise HTTPException(422, message) from None
            video = Video(
                id=video_id, filename=display_filename(file.filename), info=info.model_dump()
            )
            persistence_started = True
            with database.session.begin() as session:
                session.add(video)
                session.flush()
            saved = True
            return {
                "id": video.id,
                "filename": video.filename,
                "info": video.info,
                "created_at": iso_time(video.created_at),
            }
        finally:
            file.file.close()
            if not saved:
                # A connection can fail while reporting a successful COMMIT. Read
                # the row back before removing files that it may now reference.
                remove = not persistence_started
                if persistence_started:
                    try:
                        with database.session() as session:
                            remove = session.get(Video, video_id) is None
                    except Exception:
                        # With an unknown commit outcome, leave the artifact in
                        # place until the database can be checked again.
                        logger.exception("Upload cleanup deferred for video %s", video_id)
                if remove:
                    storage.delete(directory)

    @private.get("/videos/{video_id}/preview", tags=["Videos"])
    def preview(video_id: str):
        with database.session() as session:
            if session.get(Video, get_id(video_id)) is None:
                raise HTTPException(404, "Video not found.")
        path = storage.video_dir(video_id) / "preview.jpg"
        if not path.is_file():
            raise HTTPException(404, "Preview is unavailable.")
        return FileResponse(path, media_type="image/jpeg")

    @private.delete("/videos/{video_id}", status_code=204, tags=["Videos"])
    def delete_video(video_id: str):
        video_id = get_id(video_id)
        try:
            with database.session.begin() as session:
                if session.scalar(
                    select(func.count()).select_from(Job).where(Job.video_id == video_id)
                ):
                    raise HTTPException(409, "Delete the jobs using this video first.")
                if session.execute(delete(Video).where(Video.id == video_id)).rowcount != 1:
                    raise HTTPException(404, "Video not found.")
        except IntegrityError:
            raise HTTPException(409, "This video is used by an analysis job.") from None
        storage.delete(storage.video_dir(video_id))

    @private.post("/jobs", response_model=JobResponse, status_code=201, tags=["Jobs"])
    def start_job(body: JobRequest):
        if body.configuration.device == "cuda:0" and not settings.gpu_enabled:
            raise HTTPException(422, "GPU analysis is not enabled on this server. Select CPU.")
        with database.session.begin() as session:
            video = session.get(Video, get_id(body.video_id))
            if video is None:
                raise HTTPException(404, "Video not found.")
            job = Job(
                id=str(uuid.uuid4()),
                video_id=video.id,
                configuration=body.configuration.model_dump(),
            )
            session.add(job)
            session.flush()
            data = job_response(job, video)
        dispatch_job(database, settings, job.id, job.attempt, dispatcher)
        return data

    @private.get("/jobs", response_model=JobPage, tags=["Jobs"])
    def list_jobs(
        limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)
    ):
        with database.session() as session:
            total = session.scalar(select(func.count()).select_from(Job))
            rows = session.execute(
                select(Job, Video)
                .join(Video)
                .order_by(Job.created_at.desc(), Job.id)
                .offset(offset)
                .limit(limit)
            ).all()
            return {"items": [job_response(job, video) for job, video in rows], "total": total}

    @private.get("/jobs/{job_id}", response_model=JobResponse, tags=["Jobs"])
    def get_job(job_id: str):
        with database.session() as session:
            job = find_job(session, job_id)
            return job_response(job, session.get(Video, job.video_id))

    @private.post("/jobs/{job_id}/cancel", response_model=JobResponse, tags=["Jobs"])
    def cancel_job(job_id: str):
        with database.session.begin() as session:
            job = find_job(session, job_id)
            if job.status in TERMINAL:
                raise HTTPException(409, "Only queued or running jobs can be canceled.")
            # Conditional updates protect a concurrent worker claim and final publication.
            changed = session.execute(
                update(Job)
                .where(Job.id == job.id, Job.attempt == job.attempt, Job.status == "queued")
                .values(status="canceled", cancel_requested=True, finished_at=time.time())
            ).rowcount
            if not changed:
                changed = session.execute(
                    update(Job)
                    .where(Job.id == job.id, Job.attempt == job.attempt, Job.status == "running")
                    .values(cancel_requested=True)
                ).rowcount
            if not changed:
                raise HTTPException(409, "The job has already finished.")
            session.refresh(job)
            return job_response(job, session.get(Video, job.video_id))

    @private.post("/jobs/{job_id}/retry", response_model=JobResponse, tags=["Jobs"])
    def retry_job(job_id: str):
        with database.session.begin() as session:
            job = find_job(session, job_id)
            if job.status not in {"failed", "canceled"}:
                raise HTTPException(409, "Only failed or canceled jobs can be retried.")
            changed = session.execute(
                update(Job)
                .where(
                    Job.id == job.id,
                    Job.attempt == job.attempt,
                    Job.status.in_(["failed", "canceled"]),
                )
                .values(
                    status="queued",
                    attempt=job.attempt + 1,
                    run_token=None,
                    cancel_requested=False,
                    progress=0,
                    processed_frames=0,
                    processing_seconds=None,
                    throughput_fps=None,
                    started_at=None,
                    finished_at=None,
                    heartbeat_at=None,
                    last_dispatched_at=None,
                    error=None,
                    result_path=None,
                    summary=None,
                )
            ).rowcount
            if changed != 1:
                raise HTTPException(409, "This job was already retried.")
            session.refresh(job)
            data = job_response(job, session.get(Video, job.video_id))
        dispatch_job(database, settings, job.id, job.attempt, dispatcher)
        return data

    def completed_job(session, job_id):
        job = find_job(session, job_id)
        if job.status != "succeeded" or not job.result_path:
            raise HTTPException(409, "Results are available after the analysis succeeds.")
        return job

    @private.get("/jobs/{job_id}/result", tags=["Results"])
    def result(job_id: str):
        with database.session() as session:
            return completed_job(session, job_id).summary

    @private.get("/jobs/{job_id}/events", tags=["Results"])
    def events(
        job_id: str,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        with database.session() as session:
            job = completed_job(session, job_id)
            condition = (Event.job_id == job.id, Event.attempt == job.attempt)
            total = session.scalar(select(func.count()).select_from(Event).where(*condition))
            rows = session.scalars(
                select(Event).where(*condition).order_by(Event.id).offset(offset).limit(limit)
            )
            return {
                "items": [
                    {
                        "run_id": item.run_id,
                        "track_id": item.track_id,
                        "class_name": item.class_name,
                        "line_id": item.line_id,
                        "direction": item.direction,
                        "timestamp_video": item.timestamp_video,
                    }
                    for item in rows
                ],
                "total": total,
            }

    def result_file(job_id: str, filename: str, media_type: str, download=False):
        with database.session() as session:
            job = completed_job(session, job_id)
            path = storage.resolve(job.result_path) / filename
        if not path.is_file():
            raise HTTPException(
                404, "Result file is unavailable. Check the persistent storage volume."
            )
        return FileResponse(
            path,
            media_type=media_type,
            filename=f"trafficvision-{job_id}.{filename.rsplit('.', 1)[-1]}" if download else None,
        )

    @private.get("/jobs/{job_id}/video", tags=["Results"])
    def result_video(job_id: str):
        return result_file(job_id, "annotated.mp4", "video/mp4")

    @private.get("/jobs/{job_id}/export", tags=["Results"])
    def export(job_id: str, format: Literal["json", "csv"] = "json"):
        return result_file(
            job_id,
            "result.json" if format == "json" else "events.csv",
            "application/json" if format == "json" else "text/csv",
            download=True,
        )

    @private.delete("/jobs/{job_id}", status_code=204, tags=["Jobs"])
    def delete_job(job_id: str):
        with database.session.begin() as session:
            job = find_job(session, job_id)
            if job.status not in TERMINAL:
                raise HTTPException(
                    409, "Cancel the job and wait for it to finish before deleting it."
                )
            if (
                session.execute(
                    delete(Job).where(
                        Job.id == job.id, Job.attempt == job.attempt, Job.status.in_(TERMINAL)
                    )
                ).rowcount
                != 1
            ):
                raise HTTPException(409, "This job has changed. Refresh and try again.")
        storage.delete(storage.resolve(f"results/{get_id(job_id)}"))

    app.include_router(public)
    app.include_router(private)
    return app


app = create_app()
