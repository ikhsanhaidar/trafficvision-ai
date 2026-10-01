"""Private video metadata, fenced analysis jobs and unique crossing events."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "videos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(240), nullable=False),
        sa.Column("info", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "video_id",
            sa.String(36),
            sa.ForeignKey("videos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("run_token", sa.String(36)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("processed_frames", sa.Integer(), nullable=False),
        sa.Column("processing_seconds", sa.Float()),
        sa.Column("throughput_fps", sa.Float()),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float()),
        sa.Column("finished_at", sa.Float()),
        sa.Column("heartbeat_at", sa.Float()),
        sa.Column("last_dispatched_at", sa.Float()),
        sa.Column("error", sa.Text()),
        sa.Column("result_path", sa.String(240)),
        sa.Column("summary", sa.JSON()),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','canceled')", name="job_status"
        ),
    )
    op.create_index("ix_jobs_video_id", "jobs", ["video_id"])
    op.create_index("ix_jobs_status_heartbeat", "jobs", ["status", "heartbeat_at"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(80), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("class_name", sa.String(20), nullable=False),
        sa.Column("line_id", sa.String(40), nullable=False),
        sa.Column("direction", sa.String(12), nullable=False),
        sa.Column("timestamp_video", sa.Float(), nullable=False),
        sa.UniqueConstraint(
            "job_id", "attempt", "track_id", "line_id", "direction", name="unique_crossing"
        ),
    )
    op.create_index("ix_events_job_attempt_id", "events", ["job_id", "attempt", "id"])


def downgrade():
    op.drop_table("events")
    op.drop_table("jobs")
    op.drop_table("videos")
