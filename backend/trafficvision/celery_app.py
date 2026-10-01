"""Run one inference worker process per allocated CPU/GPU device."""

from functools import lru_cache

from celery import Celery

from trafficvision.db import Database
from trafficvision.jobs import recover_jobs, run_job
from trafficvision.settings import get_settings

settings = get_settings()
celery_app = Celery("trafficvision", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=2,
    broker_transport_options={
        "visibility_timeout": settings.max_job_seconds + 300,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
    },
    task_time_limit=settings.max_job_seconds + 30,
    task_soft_time_limit=settings.max_job_seconds + 15,
    task_default_queue="analysis",
    task_routes={
        "trafficvision.analyze": {"queue": "analysis"},
        "trafficvision.recover": {"queue": "maintenance"},
    },
    beat_schedule={"recover-abandoned-jobs": {"task": "trafficvision.recover", "schedule": 15.0}},
    timezone="UTC",
)


@lru_cache(maxsize=1)
def worker_database():
    return Database(settings.database_url)


@celery_app.task(name="trafficvision.analyze")
def analyze_task(job_id: str, attempt: int):
    return run_job(worker_database(), settings, job_id, attempt)


@celery_app.task(name="trafficvision.recover")
def recovery_task():
    return recover_jobs(worker_database(), settings)
