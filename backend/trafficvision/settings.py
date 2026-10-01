"""Environment configuration shared by the API, worker and migration command."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TV_", env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://trafficvision:trafficvision@localhost:5432/trafficvision"
    )
    redis_url: str = "redis://localhost:6379/0"
    storage_root: Path = Path("data")
    secret_key: str = ""
    admin_username: str = "admin"
    admin_password_hash: str = ""
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:8000"]
    cookie_secure: bool = False
    gpu_enabled: bool = False
    session_seconds: int = Field(default=28800, ge=60, le=604800)
    max_upload_bytes: int = Field(default=500 * 1024 * 1024, ge=1024)
    max_video_seconds: float = Field(default=900, ge=1, le=86400)
    max_video_dimension: int = Field(default=3840, ge=16)
    max_video_pixels: int = Field(default=3840 * 2160, ge=256)
    max_video_frames: int = Field(default=108000, ge=1)
    lease_seconds: int = Field(default=120, ge=5)
    max_job_seconds: int = Field(default=7200, ge=10)
    dispatch_retry_seconds: int = Field(default=30, ge=1)

    @field_validator("allowed_origins")
    @classmethod
    def explicit_origins(cls, values):
        from urllib.parse import urlsplit

        if not values:
            raise ValueError("At least one explicit frontend origin is required.")
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or "*" in value
            ):
                raise ValueError(
                    "Allowed origins must be explicit http(s) scheme://host[:port] values."
                )
        return values

    def validate_security(self):
        if len(self.secret_key) < 32:
            raise ValueError(
                "Set TV_SECRET_KEY to a randomly generated secret of at least 32 characters."
            )
        if not self.admin_password_hash.startswith("$argon2"):
            raise ValueError("Set TV_ADMIN_PASSWORD_HASH to an Argon2 password hash.")
        if not self.admin_username.strip():
            raise ValueError("TV_ADMIN_USERNAME cannot be empty.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
