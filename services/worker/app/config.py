"""Configuration settings for the Localized AI Video Ad Worker."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

WORKER_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = WORKER_ROOT.parent.parent
FIXTURES_DIR = WORKER_ROOT / "fixtures"
STATIC_DIR = WORKER_ROOT / "static"
RENDERS_DIR = STATIC_DIR / "renders"
AUDIO_DIR = STATIC_DIR / "audio"

DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_OWNER_ID = "00000000-0000-0000-0000-000000000099"


def _is_host_port_reachable(host: str, port: int, timeout: float = 0.2) -> bool:
    """Return True if a TCP connection to (host, port) succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_database_url(raw_url: str | None) -> str:
    """Resolve DATABASE_URL, falling back to local SQLite if localhost Postgres is offline."""
    default_sqlite = f"sqlite:///{(WORKER_ROOT / 'video_ads.db').as_posix()}"
    if not raw_url:
        return default_sqlite

    if raw_url.startswith(("postgresql://", "postgres://")):
        parsed = urlparse(raw_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        if host in ("localhost", "127.0.0.1") and not _is_host_port_reachable(host, port):
            return default_sqlite
        if raw_url.startswith("postgres://"):
            return raw_url.replace("postgres://", "postgresql://", 1)
    return raw_url


def is_redis_reachable(redis_url: str, timeout: float = 0.25) -> bool:
    """Return True if the configured Redis host/port accepts TCP connections."""
    import socket
    from urllib.parse import urlparse

    if not redis_url or redis_url.startswith("memory://"):
        return False
    parsed = urlparse(redis_url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(WORKER_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = ""
    GCP_PROJECT_ID: str = "video-pipeline-514123"
    GCS_BUCKET: str = "gs://videosaving"
    VEO_MODEL: str = "veo-3.1-generate-001"
    MOCK_VERTEX_VEO: bool = True
    REDIS_URL: str = "redis://localhost:6379/0"
    WORKER_API_KEY: str = ""
    CORS_ORIGINS: str = "*"
    GOOGLE_API_KEY: str = ""
    VERTEX_ACCESS_TOKEN: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    USE_REMOTION_CLI: bool = False
    DEFAULT_DURATION_SECONDS: float = 2.0

    @property
    def effective_database_url(self) -> str:
        env_override = os.environ.get("DATABASE_URL")
        url_to_check = env_override if env_override is not None else self.DATABASE_URL
        return resolve_database_url(url_to_check)

    @property
    def is_mock_veo(self) -> bool:
        env_val = os.environ.get("MOCK_VERTEX_VEO")
        if env_val is not None:
            return env_val.strip().lower() in ("1", "true", "yes", "on")
        return bool(self.MOCK_VERTEX_VEO)

    @property
    def effective_worker_api_key(self) -> str:
        env_val = os.environ.get("WORKER_API_KEY")
        return (env_val if env_val is not None else self.WORKER_API_KEY).strip()

    @property
    def effective_cors_origins(self) -> list[str]:
        env_val = os.environ.get("CORS_ORIGINS")
        raw = (env_val if env_val is not None else self.CORS_ORIGINS).strip()
        if not raw or raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def effective_google_api_key(self) -> str:
        env_val = os.environ.get("GOOGLE_API_KEY")
        return (env_val if env_val is not None else self.GOOGLE_API_KEY).strip()

    @property
    def effective_vertex_access_token(self) -> str:
        env_val = os.environ.get("VERTEX_ACCESS_TOKEN")
        return (env_val if env_val is not None else self.VERTEX_ACCESS_TOKEN).strip()

    @property
    def effective_stripe_secret_key(self) -> str:
        env_val = os.environ.get("STRIPE_SECRET_KEY")
        return (env_val if env_val is not None else self.STRIPE_SECRET_KEY).strip()

    @property
    def use_remotion_cli(self) -> bool:
        env_val = os.environ.get("USE_REMOTION_CLI")
        if env_val is not None:
            return env_val.strip().lower() in ("1", "true", "yes", "on")
        return bool(self.USE_REMOTION_CLI)


settings = Settings()

for _directory in (FIXTURES_DIR, STATIC_DIR, RENDERS_DIR, AUDIO_DIR):
    _directory.mkdir(parents=True, exist_ok=True)
