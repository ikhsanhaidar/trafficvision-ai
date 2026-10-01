"""Fenced job execution, outbox dispatch, cooperative cancellation and lease recovery."""

import json
import logging
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy import insert, or_, select, update

from trafficvision.db import Database, Event, Job, Video
from trafficvision.schemas import AnalysisConfig, CrossingEvent, VideoInfo
from trafficvision.settings import Settings
from trafficvision.storage import Storage

logger = logging.getLogger("trafficvision.jobs")
TERMINAL = {"succeeded", "failed", "canceled"}


def log_event(event: str, job_id: str | None = None, **details):
    logger.info(json.dumps({"event": event, "job_id": job_id, **details}))


def dispatch_job(
    database: Database, settings: Settings, job_id: str, attempt: int, dispatcher=None
) -> bool:
    """The committed queued row is the outbox. Repeated deliveries are safe."""
    try:
        if dispatcher is None:
            from trafficvision.celery_app import analyze_task

            analyze_task.apply_async(args=[job_id, attempt], retry=False)
        else:
            dispatcher(job_id, attempt)
        with database.session.begin() as session:
            session.execute(
                update(Job)
                .where(Job.id == job_id, Job.attempt == attempt, Job.status == "queued")
                .values(last_dispatched_at=time.time())
            )
        return True
    except Exception:
        logger.exception(
            json.dumps({"event": "dispatch_deferred", "job_id": job_id, "attempt": attempt})
        )
        return False


class Heartbeat:
    """Keep the lease alive while model loading/encoding cannot emit progress."""

    def __init__(
        self, database: Database, settings: Settings, job_id: str, attempt: int, token: str
    ):
        self.database, self.settings = database, settings
        self.job_id, self.attempt, self.token = job_id, attempt, token
        self.canceled = threading.Event()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name=f"heartbeat-{job_id}")

    def predicate(self):
        return (
            Job.id == self.job_id,
            Job.attempt == self.attempt,
            Job.run_token == self.token,
            Job.status == "running",
        )

    def _tick(self):
        now = time.time()
        with self.database.session.begin() as session:
            job = session.scalar(select(Job).where(*self.predicate()))
            if (
                job is None
                or job.cancel_requested
                or now - job.started_at > self.settings.max_job_seconds
            ):
                self.canceled.set()
                return
            session.execute(update(Job).where(*self.predicate()).values(heartbeat_at=now))

    def _loop(self):
        while not self.stopped.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception(json.dumps({"event": "heartbeat_failed", "job_id": self.job_id}))
                # Losing database ownership is treated conservatively: never publish unchecked work.
                self.canceled.set()
            if self.stopped.wait(min(2.0, self.settings.lease_seconds / 3)):
                return

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.thread.join(timeout=5)


def _public_failure(exc: Exception) -> str:
    """Keep machine paths, credentials and internal stack traces out of API errors."""
    message = str(exc).lower()
    if "cuda" in message or "out of memory" in message:
        return "The requested GPU is unavailable or has insufficient memory. Retry using CPU or a smaller inference resolution."
    if isinstance(exc, FileNotFoundError) or "checkpoint" in message:
        return "The video or model checkpoint is unavailable. Check worker storage and MODEL_CHECKPOINT, then retry."
    if "decode" in message or "video" in message or "encod" in message:
        return "Video decoding or result encoding failed. Verify the source file and worker codec support, then retry."
    return "Analysis failed. Check worker logs using this job ID, correct the cause, and retry."


def _import_events(session, path: Path, job_id: str, attempt: int, canceled):
    batch = []
    expected_run = f"{job_id}:{attempt}"
    with path.open(encoding="utf-8") as file:
        for line in file:
            data = CrossingEvent.model_validate_json(line).model_dump()
            if data["run_id"] != expected_run:
                raise ValueError("Result contains events from another run.")
            batch.append({**data, "job_id": job_id, "attempt": attempt})
            if len(batch) >= 500:
                if canceled():
                    from trafficvision.pipeline import AnalysisCanceled

                    raise AnalysisCanceled("Analysis canceled while publishing results.")
                session.execute(insert(Event), batch)
                batch.clear()
        if batch:
            session.execute(insert(Event), batch)


def run_job(
    database: Database, settings: Settings, job_id: str, attempt: int, *, analyzer=None
) -> bool:
    """A delivery must claim exactly its queued attempt before touching the pipeline."""
    token, now = str(uuid.uuid4()), time.time()
    with database.session.begin() as session:
        claim = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.attempt == attempt,
                Job.status == "queued",
                Job.cancel_requested.is_(False),
            )
            .values(
                status="running",
                run_token=token,
                started_at=now,
                heartbeat_at=now,
                finished_at=None,
                error=None,
            )
        )
        if claim.rowcount != 1:
            log_event("delivery_ignored", job_id, attempt=attempt)
            return False
        job = session.get(Job, job_id)
        video = session.get(Video, job.video_id)
        source_id, video_info, configuration = video.id, video.info, job.configuration
    storage = Storage(settings.storage_root)
    result_dir = storage.result_dir(job_id, attempt, token)
    monitor = Heartbeat(database, settings, job_id, attempt, token)
    monitor.start()
    log_event("analysis_started", job_id, attempt=attempt)
    last_progress = 0.0
    published = False

    def progress(value: float, frames: int):
        nonlocal last_progress
        current = time.monotonic()
        if current - last_progress < 1 and value < 1:
            return
        last_progress = current
        elapsed = max(time.time() - now, 0.001)
        with database.session.begin() as session:
            session.execute(
                update(Job)
                .where(*monitor.predicate())
                .values(
                    progress=max(0, min(float(value), 1)),
                    processed_frames=frames,
                    processing_seconds=elapsed,
                    throughput_fps=frames / elapsed,
                )
            )

    try:
        from trafficvision.pipeline import AnalysisCanceled, analyze_video

        summary = (analyzer or analyze_video)(
            storage.video_dir(source_id) / "source",
            result_dir,
            AnalysisConfig.model_validate(configuration),
            run_id=f"{job_id}:{attempt}",
            progress=progress,
            canceled=monitor.canceled.is_set,
            video_info=VideoInfo.model_validate(video_info),
        )
        # Atomic directory rename is handled by the pipeline. The DB pointer is published last.
        with database.session.begin() as session:
            _import_events(
                session, result_dir / "events.jsonl", job_id, attempt, monitor.canceled.is_set
            )
            updated = session.execute(
                update(Job)
                .where(*monitor.predicate(), Job.cancel_requested.is_(False))
                .values(
                    status="succeeded",
                    progress=1,
                    finished_at=time.time(),
                    processing_seconds=summary["processing_seconds"],
                    throughput_fps=summary["throughput_fps"],
                    processed_frames=summary["processed_frames"],
                    summary=summary,
                    result_path=result_dir.relative_to(storage.root).as_posix(),
                )
            )
            if updated.rowcount != 1 or monitor.canceled.is_set():
                raise AnalysisCanceled("Attempt no longer owns this job.")
        published = True
        log_event("analysis_succeeded", job_id, attempt=attempt)
        return True
    except Exception as exc:
        from trafficvision.pipeline import AnalysisCanceled

        with database.session.begin() as session:
            job = session.scalar(select(Job).where(*monitor.predicate()))
            if job is not None:
                was_canceled = job.cancel_requested
                message = (
                    None
                    if was_canceled
                    else (
                        "Analysis lost its lease or exceeded the maximum processing time. Retry the job."
                        if isinstance(exc, AnalysisCanceled)
                        else _public_failure(exc)
                    )
                )
                session.execute(
                    update(Job)
                    .where(*monitor.predicate())
                    .values(
                        status="canceled" if was_canceled else "failed",
                        error=message,
                        finished_at=time.time(),
                        processing_seconds=max(time.time() - now, 0),
                    )
                )
        logger.exception(
            json.dumps({"event": "analysis_stopped", "job_id": job_id, "attempt": attempt})
        )
        return False
    finally:
        monitor.stop()
        if not published:
            # A lost connection during COMMIT can leave its outcome unknown. Never
            # remove an artifact that a committed row references; defer on DB failure.
            try:
                with database.session() as session:
                    referenced = session.scalar(
                        select(Job.id).where(
                            Job.result_path == result_dir.relative_to(storage.root).as_posix()
                        )
                    )
                if referenced is None:
                    storage.delete(result_dir)
            except Exception:
                logger.exception(
                    json.dumps({"event": "cleanup_deferred", "job_id": job_id, "attempt": attempt})
                )


def recover_jobs(database: Database, settings: Settings, *, dispatcher=None) -> dict:
    """Scheduled by Celery beat; leases and maximum wall time bound abandoned work."""
    now = time.time()
    expired = or_(
        Job.heartbeat_at < now - settings.lease_seconds,
        Job.heartbeat_at.is_(None),
        Job.started_at < now - settings.max_job_seconds,
    )
    failed = canceled = 0
    with database.session.begin() as session:
        canceled = session.execute(
            update(Job)
            .where(Job.status == "running", expired, Job.cancel_requested.is_(True))
            .values(status="canceled", finished_at=now, error=None)
        ).rowcount
        failed = session.execute(
            update(Job)
            .where(Job.status == "running", expired, Job.cancel_requested.is_(False))
            .values(
                status="failed",
                finished_at=now,
                error="Worker stopped responding or exceeded the maximum processing time. Retry this job.",
            )
        ).rowcount
        queued = session.execute(
            select(Job.id, Job.attempt)
            .where(
                Job.status == "queued",
                Job.cancel_requested.is_(False),
                or_(
                    Job.last_dispatched_at.is_(None),
                    Job.last_dispatched_at < now - settings.dispatch_retry_seconds,
                ),
            )
            .order_by(Job.created_at)
            .limit(100)
        ).all()
    dispatched = sum(
        dispatch_job(database, settings, job_id, attempt, dispatcher) for job_id, attempt in queued
    )
    result = {"failed": failed, "canceled": canceled, "dispatched": dispatched}
    result["cleaned_directories"] = clean_abandoned_results(database, settings, now=now)
    log_event("recovery_finished", **result)
    return result


def clean_abandoned_results(
    database: Database, settings: Settings, *, now: float | None = None
) -> int:
    """Reap hard-kill leftovers only after a terminal-state grace period.

    Lock the job while cleaning so a concurrent retry cannot become active here.
    Successful referenced output and every queued/running job are preserved.
    """
    storage = Storage(settings.storage_root)
    root = storage.resolve("results")
    cutoff = (now if now is not None else time.time()) - settings.lease_seconds
    cleaned = 0
    if not root.is_dir():
        return 0
    for directory in root.iterdir():
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            job_id = str(uuid.UUID(directory.name))
        except ValueError:
            continue
        with database.session.begin() as session:
            job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if job is not None and (
                job.status not in TERMINAL or not job.finished_at or job.finished_at > cutoff
            ):
                continue
            keep = storage.resolve(job.result_path) if job and job.result_path else None
            for artifact in directory.iterdir():
                try:
                    if (
                        artifact.is_symlink()
                        or artifact.resolve() == keep
                        or artifact.stat().st_mtime > cutoff
                    ):
                        continue
                    storage.delete(artifact)
                    cleaned += 1
                except OSError:
                    # A concurrent delete or a stale process with open files must
                    # not prevent later scheduled recovery and outbox dispatch.
                    logger.warning(json.dumps({"event": "cleanup_deferred", "job_id": job_id}))
    return cleaned
