"""Lifecycle and fencing tests with independent DB sessions and actual worker threads."""

import os
import threading
import time
import uuid

from sqlalchemy import func, select, update
from test_api import pipeline_analyzer, start, upload
from test_api import service as service_fixture
from trafficvision.db import Event, Job
from trafficvision.jobs import clean_abandoned_results, dispatch_job, recover_jobs, run_job
from trafficvision.pipeline import AnalysisCanceled
from trafficvision.storage import Storage

service = service_fixture


def test_cancel_queued_retry_and_stale_delivery_are_fenced(service, synthetic_video):
    job = start(service, upload(service, synthetic_video()))
    canceled = service.client.post(f"/api/jobs/{job['id']}/cancel").json()
    assert canceled["status"] == "canceled"
    assert not run_job(service.database, service.settings, job["id"], 1, analyzer=pipeline_analyzer)
    retry = service.client.post(f"/api/jobs/{job['id']}/retry").json()
    assert retry["attempt"] == 2 and retry["status"] == "queued"
    assert not run_job(service.database, service.settings, job["id"], 1, analyzer=pipeline_analyzer)
    assert run_job(service.database, service.settings, job["id"], 2, analyzer=pipeline_analyzer)
    assert not run_job(service.database, service.settings, job["id"], 2, analyzer=pipeline_analyzer)
    with service.database.session() as session:
        events = list(session.scalars(select(Event)))
        assert len(events) == 2 and {event.attempt for event in events} == {2}
        assert {event.run_id for event in events} == {f"{job['id']}:2"}


def test_failed_job_can_retry_without_duplicate_events(service, synthetic_video):
    job = start(service, upload(service, synthetic_video()))

    def failing(*args, **kwargs):
        raise RuntimeError("Synthetic encoding failure with private internal information")

    assert not run_job(service.database, service.settings, job["id"], 1, analyzer=failing)
    failed = service.client.get(f"/api/jobs/{job['id']}").json()
    assert failed["status"] == "failed" and "encoding" in failed["error"]
    assert "private internal information" not in failed["error"]
    assert service.client.post(f"/api/jobs/{job['id']}/retry").status_code == 200
    assert run_job(service.database, service.settings, job["id"], 2, analyzer=pipeline_analyzer)
    assert service.client.post(f"/api/jobs/{job['id']}/retry").status_code == 409
    assert service.client.get(f"/api/jobs/{job['id']}/events").json()["total"] == 2


def test_running_cancel_observed_during_model_load_and_no_result_published(
    service, synthetic_video
):
    job = start(service, upload(service, synthetic_video()))
    entered = threading.Event()

    def loading(*args, **kwargs):
        entered.set()
        deadline = time.monotonic() + 10
        while not kwargs["canceled"]() and time.monotonic() < deadline:
            entered.wait(0.02)
            time.sleep(0.01)
        assert kwargs["canceled"](), "Heartbeat must observe cancellation without frame progress"
        raise AnalysisCanceled("Synthetic long model load canceled")

    thread = threading.Thread(
        target=run_job,
        args=(service.database, service.settings, job["id"], 1),
        kwargs={"analyzer": loading},
    )
    thread.start()
    assert entered.wait(5)
    response = service.client.post(f"/api/jobs/{job['id']}/cancel")
    assert response.status_code == 200 and response.json()["cancel_requested"]
    thread.join(12)
    assert not thread.is_alive()
    detail = service.client.get(f"/api/jobs/{job['id']}").json()
    assert detail["status"] == "canceled" and detail["summary"] is None
    assert service.client.get(f"/api/jobs/{job['id']}/video").status_code == 409


def test_concurrent_duplicate_delivery_cannot_run_two_analyzers(service, synthetic_video):
    job = start(service, upload(service, synthetic_video()))
    entered, release = threading.Event(), threading.Event()
    calls = []

    def analyzer(*args, **kwargs):
        calls.append(kwargs["run_id"])
        entered.set()
        assert release.wait(5)
        return pipeline_analyzer(*args, **kwargs)

    thread = threading.Thread(
        target=run_job,
        args=(service.database, service.settings, job["id"], 1),
        kwargs={"analyzer": analyzer},
    )
    thread.start()
    assert entered.wait(5)
    try:
        assert not run_job(service.database, service.settings, job["id"], 1, analyzer=analyzer)
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and calls == [f"{job['id']}:1"]
    assert service.client.get(f"/api/jobs/{job['id']}/events").json()["total"] == 2


def test_recovery_marks_expired_and_wall_time_jobs_and_redelivers_outbox(service, synthetic_video):
    video = upload(service, synthetic_video())
    expired, canceled, too_long, queued = [start(service, video) for _ in range(4)]
    now = time.time()
    with service.database.session.begin() as session:
        for item in [expired, canceled]:
            session.execute(
                update(Job)
                .where(Job.id == item["id"])
                .values(
                    status="running",
                    started_at=now - 20,
                    heartbeat_at=now - 10,
                    cancel_requested=item == canceled,
                )
            )
        session.execute(
            update(Job)
            .where(Job.id == too_long["id"])
            .values(status="running", started_at=now - 100, heartbeat_at=now)
        )
        session.execute(update(Job).where(Job.id == queued["id"]).values(last_dispatched_at=None))
    sent = []
    result = recover_jobs(
        service.database, service.settings, dispatcher=lambda *args: sent.append(args)
    )
    assert result["failed"] == 2 and result["canceled"] == 1 and result["dispatched"] == 1
    assert sent == [(queued["id"], 1)]
    assert service.client.get(f"/api/jobs/{expired['id']}").json()["status"] == "failed"
    assert service.client.get(f"/api/jobs/{canceled['id']}").json()["status"] == "canceled"


def test_broker_failure_remains_in_outbox_for_recovery(service, synthetic_video):
    job = start(service, upload(service, synthetic_video()))
    with service.database.session.begin() as session:
        session.execute(update(Job).where(Job.id == job["id"]).values(last_dispatched_at=None))

    def unavailable(*args):
        raise ConnectionError("Synthetic broker unavailable")

    assert not dispatch_job(service.database, service.settings, job["id"], 1, unavailable)
    with service.database.session() as session:
        stored = session.get(Job, job["id"])
        assert stored.status == "queued" and stored.last_dispatched_at is None
    sent = []
    recover_jobs(service.database, service.settings, dispatcher=lambda *args: sent.append(args))
    assert sent == [(job["id"], 1)]


def test_late_completion_cannot_replace_retried_attempt(service, synthetic_video):
    job = start(service, upload(service, synthetic_video()))

    def ownership_changed(*args, **kwargs):
        summary = pipeline_analyzer(*args, **kwargs)
        with service.database.session.begin() as session:
            # Represents recovery plus a user retry while the old worker was disconnected.
            session.execute(
                update(Job)
                .where(Job.id == job["id"])
                .values(status="queued", attempt=2, run_token=None, heartbeat_at=None)
            )
        return summary

    assert not run_job(service.database, service.settings, job["id"], 1, analyzer=ownership_changed)
    with service.database.session() as session:
        stored = session.get(Job, job["id"])
        assert stored.status == "queued" and stored.attempt == 2 and stored.result_path is None
        assert session.scalar(select(func.count()).select_from(Event)) == 0
    assert list((service.settings.storage_root / "results" / job["id"]).iterdir()) == []
    assert run_job(service.database, service.settings, job["id"], 2, analyzer=pipeline_analyzer)


def test_duplicate_events_roll_back_entire_publication(service, synthetic_video):
    job = start(service, upload(service, synthetic_video()))

    def duplicate(*args, **kwargs):
        summary = pipeline_analyzer(*args, **kwargs)
        path = args[1] / "events.jsonl"
        contents = path.read_text(encoding="utf-8")
        path.write_text(contents + contents.splitlines()[0] + "\n", encoding="utf-8")
        return summary

    assert not run_job(service.database, service.settings, job["id"], 1, analyzer=duplicate)
    with service.database.session() as session:
        stored = session.get(Job, job["id"])
        assert stored.status == "failed" and stored.result_path is None and stored.summary is None
        assert session.scalar(select(func.count()).select_from(Event)) == 0
    assert list((service.settings.storage_root / "results" / job["id"]).iterdir()) == []


def test_uncertain_commit_cleanup_preserves_referenced_result(service, synthetic_video):
    job = start(service, upload(service, synthetic_video()))
    storage = Storage(service.settings.storage_root)
    committed = []

    def commit_then_disconnect(*args, **kwargs):
        summary = pipeline_analyzer(*args, **kwargs)
        path = args[1]
        with service.database.session.begin() as session:
            session.execute(
                update(Job)
                .where(Job.id == job["id"])
                .values(
                    status="succeeded",
                    result_path=path.relative_to(storage.root).as_posix(),
                    summary=summary,
                    finished_at=time.time(),
                )
            )
        committed.append(path)
        # Model a commit accepted by the DB before the client observes connection loss.
        raise ConnectionError("Synthetic response lost after commit")

    assert not run_job(
        service.database, service.settings, job["id"], 1, analyzer=commit_then_disconnect
    )
    assert committed[0].is_dir()
    assert service.client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"
    assert service.client.get(f"/api/jobs/{job['id']}/video").status_code == 200


def test_reaper_preserves_active_and_referenced_results(service, synthetic_video):
    video = upload(service, synthetic_video())
    success, active, failed = [start(service, video) for _ in range(3)]
    assert run_job(service.database, service.settings, success["id"], 1, analyzer=pipeline_analyzer)
    storage = Storage(service.settings.storage_root)
    old = time.time() - 100
    active_dir = storage.result_dir(active["id"], 1, str(uuid.uuid4()))
    abandoned = storage.result_dir(failed["id"], 1, str(uuid.uuid4()))
    success_extra = storage.result_dir(success["id"], 1, str(uuid.uuid4()))
    temporary = abandoned.parent / f".{abandoned.name}.temporary.tmp"
    for path in [active_dir, abandoned, success_extra, temporary]:
        path.mkdir(parents=True)
        (path / "partial").write_text("synthetic leftover")
        os.utime(path, (old, old))
    with service.database.session.begin() as session:
        session.execute(
            update(Job).where(Job.id == failed["id"]).values(status="failed", finished_at=old)
        )
        session.execute(update(Job).where(Job.id == success["id"]).values(finished_at=old))
        keep = storage.resolve(session.get(Job, success["id"]).result_path)
        os.utime(keep, (old, old))
    assert clean_abandoned_results(service.database, service.settings) == 3
    assert active_dir.is_dir() and keep.is_dir()
    assert not abandoned.exists() and not success_extra.exists() and not temporary.exists()
