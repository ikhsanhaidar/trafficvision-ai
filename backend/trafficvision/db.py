"""Metadata and lifecycle state. Each worker thread owns its database session."""

import time

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(240))
    info: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','canceled')", name="job_status"
        ),
        Index("ix_jobs_status_heartbeat", "status", "heartbeat_at"),
        Index("ix_jobs_created_at", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    configuration: Mapped[dict] = mapped_column(JSON)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    run_token: Mapped[str | None] = mapped_column(String(36))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[float] = mapped_column(Float, default=0)
    processed_frames: Mapped[int] = mapped_column(Integer, default=0)
    processing_seconds: Mapped[float | None] = mapped_column(Float)
    throughput_fps: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    started_at: Mapped[float | None] = mapped_column(Float)
    finished_at: Mapped[float | None] = mapped_column(Float)
    heartbeat_at: Mapped[float | None] = mapped_column(Float)
    last_dispatched_at: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    result_path: Mapped[str | None] = mapped_column(String(240))
    summary: Mapped[dict | None] = mapped_column(JSON)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "attempt", "track_id", "line_id", "direction", name="unique_crossing"
        ),
        Index("ix_events_job_attempt_id", "job_id", "attempt", "id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    attempt: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(String(80))
    track_id: Mapped[int] = mapped_column(Integer)
    class_name: Mapped[str] = mapped_column(String(20))
    line_id: Mapped[str] = mapped_column(String(40))
    direction: Mapped[str] = mapped_column(String(12))
    timestamp_video: Mapped[float] = mapped_column(Float)


class Database:
    def __init__(self, url: str):
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self.engine = create_engine(url, **options)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def sqlite_foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")

        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self):
        """Used only by isolated tests; production uses Alembic migrations."""
        Base.metadata.create_all(self.engine)

    def dispose(self):
        self.engine.dispose()
