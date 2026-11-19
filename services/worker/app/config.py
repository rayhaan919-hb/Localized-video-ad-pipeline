"""Configuration settings and production validation for the Localized AI Video Ad Worker."""

from __future__ import annotations

import os
import secrets
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

WORKER_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = WORKER_ROOT.parent.parent
FIXTURES_DIR = WORKER_ROOT / "fixtures"
STATIC_DIR = WORKER_ROOT / "static"
RENDERS_DIR = STATIC_DIR / "renders"
AUDIO_DIR = STATIC_DIR / "audio"
STORAGE_DIR = WORKER_ROOT / "storage"

# Process-local ephemeral secrets used strictly in development/test when unset in env.
_DEV_EPHEMERAL_JWT_SECRET = secrets.token_hex(32)
_DEV_EPHEMERAL_SIGNED_URL_SECRET = secrets.token_hex(32)

CREDIT_PACKAGES: dict[str, dict[str, Any]] = {
    "starter_10": {
        "pack_id": "starter_10",
        "name": "Starter Pack",
        "credits": 10,
        "amount_cents": 900,
        "currency": "usd",
        "price_env_key": "STRIPE_PRICE_STARTER_10",
    },
    "growth_50": {
        "pack_id": "growth_50",
        "name": "Growth Pack",
        "credits": 50,
        "amount_cents": 3900,
        "currency": "usd",
        "price_env_key": "STRIPE_PRICE_GROWTH_50",
    },
    "scale_200": {
        "pack_id": "scale_200",
        "name": "Scale Pack",
        "credits": 200,
        "amount_cents": 12900,
        "currency": "usd",
        "price_env_key": "STRIPE_PRICE_SCALE_200",
    },
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return int(default)
    return int(raw.strip())


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return float(default)
    return float(raw.strip())


def _is_host_port_reachable(host: str, port: int, timeout: float = 0.2) -> bool:
    """Return True if a TCP connection to (host, port) succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_database_url(raw_url: str | None, app_env: str = "development") -> str:
    """Resolve DATABASE_URL.

    In production, PostgreSQL URLs are never silently downgraded to SQLite.
    In development/test, unreachable localhost PostgreSQL falls back to local SQLite.
    """
    default_sqlite = f"sqlite:///{(WORKER_ROOT / 'video_ads.db').as_posix()}"
    cleaned = (raw_url or "").strip()
    if not cleaned:
        if app_env == "production":
            return ""
        return default_sqlite

    if cleaned.startswith("postgres://"):
        cleaned = cleaned.replace("postgres://", "postgresql://", 1)

    if cleaned.startswith("postgresql://") and app_env != "production":
        parsed = urlparse(cleaned)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        if host in ("localhost", "127.0.0.1") and not _is_host_port_reachable(host, port):
            return default_sqlite

    return cleaned


def is_redis_reachable(redis_url: str, timeout: float = 0.25) -> bool:
    """Return True if the configured Redis host/port accepts TCP connections."""
    if not redis_url or redis_url.startswith("memory://"):
        return False
    parsed = urlparse(redis_url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or 6379
    return _is_host_port_reachable(host, port, timeout=timeout)


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), str(WORKER_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "development"
    DATABASE_URL: str = ""
    GCP_PROJECT_ID: str = ""
    VERTEX_LOCATION: str = "us-central1"
    GCS_BUCKET: str = ""
    VEO_MODEL: str = "veo-3.1-generate-001"
    MOCK_VERTEX_VEO: bool = False
    MOCK_TTS: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"
    WORKER_API_KEY: str = ""
    ADMIN_ADJUST_SECRET: str = ""
    AUTH_JWT_SECRET: str = ""
    SIGNED_URL_SECRET: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_JWT_SECRET: str = ""
    CORS_ORIGINS: str = "http://localhost:3000"
    ALLOW_WILDCARD_CORS: bool = False
    FRONTEND_APP_URL: str = "http://localhost:3000"
    GOOGLE_API_KEY: str = ""
    VERTEX_ACCESS_TOKEN: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    GOOGLE_CLOUD_TTS_ENDPOINT: str = "https://texttospeech.googleapis.com/v1/text:synthesize"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_CURRENCY: str = "usd"
    STRIPE_PRICE_STARTER_10: str = ""
    STRIPE_PRICE_GROWTH_50: str = ""
    STRIPE_PRICE_SCALE_200: str = ""
    INITIAL_PROMO_CREDITS: int = 3
    ENABLE_DEV_TOPUP: bool = False
    ACCESS_TOKEN_TTL_SECONDS: int = 900
    REFRESH_TOKEN_TTL_SECONDS: int = 60 * 60 * 24 * 14
    PASSWORD_RESET_TTL_SECONDS: int = 1800
    EMAIL_VERIFY_TTL_SECONDS: int = 86400
    SIGNED_URL_TTL_SECONDS: int = 3600
    MAX_REQUEST_BODY_BYTES: int = 10 * 1024 * 1024
    MAX_ASSET_UPLOAD_BYTES: int = 8 * 1024 * 1024
    RATE_LIMIT_AUTH_PER_MINUTE: int = 15
    RATE_LIMIT_API_PER_MINUTE: int = 120
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 15
    RATE_LIMIT_REGISTER_PER_MINUTE: int = 10
    RATE_LIMIT_PASSWORD_RESET_PER_MINUTE: int = 10
    RATE_LIMIT_GENERATE_PER_MINUTE: int = 30
    RATE_LIMIT_RENDER_RETRY_PER_MINUTE: int = 20
    RATE_LIMIT_SCRAPE_PER_MINUTE: int = 60
    RATE_LIMIT_DOWNLOAD_PER_MINUTE: int = 120
    RATE_LIMIT_BILLING_PER_MINUTE: int = 20
    RATE_LIMIT_BURST_WINDOW_SECONDS: int = 10
    RATE_LIMIT_BURST_MULTIPLIER: float = 0.5
    REQUIRE_REDIS_BROKER: bool = False
    REQUIRE_ACTIVE_CELERY_WORKER: bool = False
    JOB_LEASE_DURATION_SECONDS: int = 120
    JOB_HEARTBEAT_INTERVAL_SECONDS: int = 30
    JOB_UNCLAIMED_GRACE_SECONDS: int = 120
    JOB_SOFT_TIME_LIMIT_SECONDS: int = 300
    JOB_HARD_TIME_LIMIT_SECONDS: int = 360
    JOB_MAX_RETRIES: int = 3
    JOB_RETRY_BASE_DELAY_SECONDS: float = 2.0
    JOB_RETRY_MAX_DELAY_SECONDS: float = 60.0
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    AUTH_LOCKOUT_MAX_ATTEMPTS: int = 5
    AUTH_LOCKOUT_WINDOW_SECONDS: int = 900
    TRUST_PROXY_HEADERS: bool = False
    MAX_RENDERED_VIDEO_BYTES: int = 100 * 1024 * 1024
    STORAGE_ROOT: str = str(STORAGE_DIR)
    USE_REMOTION_CLI: bool = False
    DEFAULT_DURATION_SECONDS: float = 4.0
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = ""
    REQUIRE_EMAIL_VERIFICATION: bool = True
    EXPOSE_DEV_AUTH_TOKENS: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_USE_TLS: bool = True

    @property
    def effective_app_env(self) -> str:
        raw = os.environ.get("APP_ENV")
        val = (raw if raw is not None else self.APP_ENV).strip().lower()
        return val or "development"

    @property
    def is_production(self) -> bool:
        return self.effective_app_env == "production"

    @property
    def effective_database_url(self) -> str:
        env_override = os.environ.get("DATABASE_URL")
        url_to_check = env_override if env_override is not None else self.DATABASE_URL
        return resolve_database_url(url_to_check, app_env=self.effective_app_env)

    @property
    def is_mock_veo(self) -> bool:
        return _env_bool("MOCK_VERTEX_VEO", self.MOCK_VERTEX_VEO)

    @property
    def is_mock_tts(self) -> bool:
        return _env_bool("MOCK_TTS", self.MOCK_TTS)

    @property
    def effective_gcp_project_id(self) -> str:
        env_val = os.environ.get("GCP_PROJECT_ID")
        return (env_val if env_val is not None else self.GCP_PROJECT_ID).strip()

    @property
    def effective_gcs_bucket(self) -> str:
        env_val = os.environ.get("GCS_BUCKET")
        return (env_val if env_val is not None else self.GCS_BUCKET).strip()

    @property
    def effective_vertex_location(self) -> str:
        env_val = os.environ.get("VERTEX_LOCATION")
        return (env_val if env_val is not None else self.VERTEX_LOCATION).strip() or "us-central1"

    @property
    def effective_worker_api_key(self) -> str:
        env_val = os.environ.get("WORKER_API_KEY")
        return (env_val if env_val is not None else self.WORKER_API_KEY).strip()

    @property
    def effective_admin_adjust_secret(self) -> str:
        env_val = os.environ.get("ADMIN_ADJUST_SECRET")
        return (env_val if env_val is not None else self.ADMIN_ADJUST_SECRET).strip()

    @property
    def effective_auth_jwt_secret(self) -> str:
        env_val = os.environ.get("AUTH_JWT_SECRET")
        configured = (env_val if env_val is not None else self.AUTH_JWT_SECRET).strip()
        if configured:
            return configured
        if self.is_production:
            return ""
        return _DEV_EPHEMERAL_JWT_SECRET

    @property
    def effective_supabase_jwt_secret(self) -> str:
        env_val = os.environ.get("SUPABASE_JWT_SECRET")
        return (env_val if env_val is not None else self.SUPABASE_JWT_SECRET).strip()

    @property
    def effective_signed_url_secret(self) -> str:
        env_val = os.environ.get("SIGNED_URL_SECRET")
        configured = (env_val if env_val is not None else self.SIGNED_URL_SECRET).strip()
        if configured:
            return configured
        if self.effective_auth_jwt_secret:
            return self.effective_auth_jwt_secret
        if self.is_production:
            return ""
        return _DEV_EPHEMERAL_SIGNED_URL_SECRET

    @property
    def effective_cors_origins(self) -> list[str]:
        env_val = os.environ.get("CORS_ORIGINS")
        raw = (env_val if env_val is not None else self.CORS_ORIGINS).strip()
        if not raw:
            return []
        if raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def effective_frontend_app_url(self) -> str:
        env_val = os.environ.get("FRONTEND_APP_URL")
        return (env_val if env_val is not None else self.FRONTEND_APP_URL).strip().rstrip("/")

    @property
    def effective_google_api_key(self) -> str:
        env_val = os.environ.get("GOOGLE_API_KEY")
        return (env_val if env_val is not None else self.GOOGLE_API_KEY).strip()

    @property
    def effective_vertex_access_token(self) -> str:
        env_val = os.environ.get("VERTEX_ACCESS_TOKEN")
        return (env_val if env_val is not None else self.VERTEX_ACCESS_TOKEN).strip()

    @property
    def effective_google_application_credentials(self) -> str:
        env_val = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        return (env_val if env_val is not None else self.GOOGLE_APPLICATION_CREDENTIALS).strip()

    @property
    def effective_stripe_secret_key(self) -> str:
        env_val = os.environ.get("STRIPE_SECRET_KEY")
        return (env_val if env_val is not None else self.STRIPE_SECRET_KEY).strip()

    @property
    def effective_stripe_webhook_secret(self) -> str:
        env_val = os.environ.get("STRIPE_WEBHOOK_SECRET")
        return (env_val if env_val is not None else self.STRIPE_WEBHOOK_SECRET).strip()

    @property
    def effective_initial_promo_credits(self) -> int:
        return max(0, _env_int("INITIAL_PROMO_CREDITS", self.INITIAL_PROMO_CREDITS))

    @property
    def effective_enable_dev_topup(self) -> bool:
        if self.is_production:
            return False
        return _env_bool("ENABLE_DEV_TOPUP", self.ENABLE_DEV_TOPUP)

    @property
    def effective_storage_root(self) -> Path:
        env_val = os.environ.get("STORAGE_ROOT")
        raw = (env_val if env_val is not None else self.STORAGE_ROOT).strip()
        path = Path(raw) if raw else STORAGE_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def use_remotion_cli(self) -> bool:
        return _env_bool("USE_REMOTION_CLI", self.USE_REMOTION_CLI)

    @property
    def effective_trust_proxy_headers(self) -> bool:
        return _env_bool("TRUST_PROXY_HEADERS", self.TRUST_PROXY_HEADERS)

    @property
    def effective_max_rendered_video_bytes(self) -> int:
        return max(1024, _env_int("MAX_RENDERED_VIDEO_BYTES", self.MAX_RENDERED_VIDEO_BYTES))

    @property
    def effective_google_oauth_client_id(self) -> str:
        env_val = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        return (env_val if env_val is not None else self.GOOGLE_OAUTH_CLIENT_ID).strip()

    @property
    def effective_google_oauth_client_secret(self) -> str:
        env_val = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        return (env_val if env_val is not None else self.GOOGLE_OAUTH_CLIENT_SECRET).strip()

    @property
    def effective_google_oauth_redirect_uri(self) -> str:
        env_val = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
        configured = (
            env_val if env_val is not None else self.GOOGLE_OAUTH_REDIRECT_URI
        ).strip()
        if configured:
            return configured
        base = self.effective_frontend_app_url or "http://localhost:3000"
        return f"{base}/api/v1/auth/google/callback"

    @property
    def is_google_oauth_configured(self) -> bool:
        return bool(
            self.effective_google_oauth_client_id and self.effective_google_oauth_client_secret
        )

    @property
    def effective_require_email_verification(self) -> bool:
        raw = os.environ.get("REQUIRE_EMAIL_VERIFICATION")
        if raw is not None:
            return _env_bool("REQUIRE_EMAIL_VERIFICATION", True)
        if self.effective_app_env == "test":
            return False
        return bool(self.REQUIRE_EMAIL_VERIFICATION)

    @property
    def effective_expose_dev_auth_tokens(self) -> bool:
        if self.is_production:
            return False
        raw = os.environ.get("EXPOSE_DEV_AUTH_TOKENS")
        if raw is not None:
            return _env_bool("EXPOSE_DEV_AUTH_TOKENS", False)
        if self.effective_app_env == "test":
            return True
        return bool(self.EXPOSE_DEV_AUTH_TOKENS)

    @property
    def effective_smtp_host(self) -> str:
        env_val = os.environ.get("SMTP_HOST")
        return (env_val if env_val is not None else self.SMTP_HOST).strip()

    @property
    def effective_smtp_port(self) -> int:
        return max(1, _env_int("SMTP_PORT", self.SMTP_PORT))

    @property
    def effective_smtp_user(self) -> str:
        env_val = os.environ.get("SMTP_USER")
        return (env_val if env_val is not None else self.SMTP_USER).strip()

    @property
    def effective_smtp_password(self) -> str:
        env_val = os.environ.get("SMTP_PASSWORD")
        return (env_val if env_val is not None else self.SMTP_PASSWORD).strip()

    @property
    def effective_smtp_from_email(self) -> str:
        env_val = os.environ.get("SMTP_FROM_EMAIL")
        return (env_val if env_val is not None else self.SMTP_FROM_EMAIL).strip()

    @property
    def effective_smtp_use_tls(self) -> bool:
        return _env_bool("SMTP_USE_TLS", self.SMTP_USE_TLS)

    @property
    def is_smtp_configured(self) -> bool:
        return bool(self.effective_smtp_host and self.effective_smtp_from_email)

    @property
    def effective_redis_url(self) -> str:
        env_val = os.environ.get("REDIS_URL")
        return (env_val if env_val is not None else self.REDIS_URL).strip()

    @property
    def effective_require_redis_broker(self) -> bool:
        if self.is_production:
            return True
        return _env_bool("REQUIRE_REDIS_BROKER", self.REQUIRE_REDIS_BROKER)

    @property
    def effective_require_active_celery_worker(self) -> bool:
        return _env_bool("REQUIRE_ACTIVE_CELERY_WORKER", self.REQUIRE_ACTIVE_CELERY_WORKER)

    @property
    def effective_job_lease_duration_seconds(self) -> int:
        return max(10, _env_int("JOB_LEASE_DURATION_SECONDS", self.JOB_LEASE_DURATION_SECONDS))

    @property
    def effective_job_heartbeat_interval_seconds(self) -> int:
        return max(
            1, _env_int("JOB_HEARTBEAT_INTERVAL_SECONDS", self.JOB_HEARTBEAT_INTERVAL_SECONDS)
        )

    @property
    def effective_job_unclaimed_grace_seconds(self) -> int:
        return max(0, _env_int("JOB_UNCLAIMED_GRACE_SECONDS", self.JOB_UNCLAIMED_GRACE_SECONDS))

    @property
    def effective_job_soft_time_limit_seconds(self) -> int:
        return max(10, _env_int("JOB_SOFT_TIME_LIMIT_SECONDS", self.JOB_SOFT_TIME_LIMIT_SECONDS))

    @property
    def effective_job_hard_time_limit_seconds(self) -> int:
        soft = self.effective_job_soft_time_limit_seconds
        hard = max(15, _env_int("JOB_HARD_TIME_LIMIT_SECONDS", self.JOB_HARD_TIME_LIMIT_SECONDS))
        return max(soft + 5, hard)

    @property
    def effective_job_max_retries(self) -> int:
        return max(0, _env_int("JOB_MAX_RETRIES", self.JOB_MAX_RETRIES))

    @property
    def effective_job_retry_base_delay_seconds(self) -> float:
        return max(
            0.05, _env_float("JOB_RETRY_BASE_DELAY_SECONDS", self.JOB_RETRY_BASE_DELAY_SECONDS)
        )

    @property
    def effective_job_retry_max_delay_seconds(self) -> float:
        base = self.effective_job_retry_base_delay_seconds
        return max(
            base, _env_float("JOB_RETRY_MAX_DELAY_SECONDS", self.JOB_RETRY_MAX_DELAY_SECONDS)
        )

    @property
    def effective_db_pool_size(self) -> int:
        return max(1, _env_int("DB_POOL_SIZE", self.DB_POOL_SIZE))

    @property
    def effective_db_max_overflow(self) -> int:
        return max(0, _env_int("DB_MAX_OVERFLOW", self.DB_MAX_OVERFLOW))

    @property
    def effective_db_pool_timeout(self) -> int:
        return max(5, _env_int("DB_POOL_TIMEOUT", self.DB_POOL_TIMEOUT))

    @property
    def effective_db_pool_recycle(self) -> int:
        return max(60, _env_int("DB_POOL_RECYCLE", self.DB_POOL_RECYCLE))

    @property
    def effective_rate_limit_burst_window_seconds(self) -> int:
        return max(
            1, _env_int("RATE_LIMIT_BURST_WINDOW_SECONDS", self.RATE_LIMIT_BURST_WINDOW_SECONDS)
        )

    @property
    def effective_rate_limit_burst_multiplier(self) -> float:
        val = _env_float("RATE_LIMIT_BURST_MULTIPLIER", self.RATE_LIMIT_BURST_MULTIPLIER)
        return min(1.0, max(0.1, val))

    def get_rate_limit(self, category: str) -> int:
        mapping = {
            "auth_login": ("RATE_LIMIT_LOGIN_PER_MINUTE", self.RATE_LIMIT_LOGIN_PER_MINUTE),
            "auth_register": (
                "RATE_LIMIT_REGISTER_PER_MINUTE",
                self.RATE_LIMIT_REGISTER_PER_MINUTE,
            ),
            "auth_password_reset": (
                "RATE_LIMIT_PASSWORD_RESET_PER_MINUTE",
                self.RATE_LIMIT_PASSWORD_RESET_PER_MINUTE,
            ),
            "video_generate": (
                "RATE_LIMIT_GENERATE_PER_MINUTE",
                self.RATE_LIMIT_GENERATE_PER_MINUTE,
            ),
            "video_render_retry": (
                "RATE_LIMIT_RENDER_RETRY_PER_MINUTE",
                self.RATE_LIMIT_RENDER_RETRY_PER_MINUTE,
            ),
            "product_scrape": ("RATE_LIMIT_SCRAPE_PER_MINUTE", self.RATE_LIMIT_SCRAPE_PER_MINUTE),
            "file_download": (
                "RATE_LIMIT_DOWNLOAD_PER_MINUTE",
                self.RATE_LIMIT_DOWNLOAD_PER_MINUTE,
            ),
            "billing_checkout": (
                "RATE_LIMIT_BILLING_PER_MINUTE",
                self.RATE_LIMIT_BILLING_PER_MINUTE,
            ),
        }
        env_key, default_val = mapping.get(
            category, ("RATE_LIMIT_API_PER_MINUTE", self.RATE_LIMIT_API_PER_MINUTE)
        )
        specific_env = os.environ.get(env_key)
        if specific_env is not None and specific_env.strip():
            return max(1, int(specific_env.strip()))
        if category.startswith("auth_"):
            auth_env = os.environ.get("RATE_LIMIT_AUTH_PER_MINUTE")
            if auth_env is not None and auth_env.strip():
                return max(1, int(auth_env.strip()))
            if self.RATE_LIMIT_AUTH_PER_MINUTE != 15:
                return max(1, int(self.RATE_LIMIT_AUTH_PER_MINUTE))
        return max(1, int(default_val))

    def get_stripe_price_id(self, pack_id: str) -> str:
        pkg = CREDIT_PACKAGES.get(pack_id)
        if not pkg:
            return ""
        env_key = str(pkg["price_env_key"])
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return env_val.strip()
        return str(getattr(self, env_key, "")).strip()


settings = Settings()


def validate_production_config() -> None:
    """Fail closed when APP_ENV=production and required security/service settings are missing."""
    if not settings.is_production:
        return

    errors: list[str] = []

    if settings.is_mock_veo:
        errors.append("MOCK_VERTEX_VEO must be false in production.")
    if settings.is_mock_tts:
        errors.append("MOCK_TTS must be false in production.")
    if settings.effective_enable_dev_topup:
        errors.append("ENABLE_DEV_TOPUP must be false in production.")
    if _env_bool("CELERY_ALWAYS_EAGER", False):
        errors.append(
            "CELERY_ALWAYS_EAGER must be false in production; "
            "dedicated Celery workers are required."
        )

    redis_url = settings.effective_redis_url
    if not redis_url or not redis_url.startswith(("redis://", "rediss://")):
        errors.append("REDIS_URL must be configured with redis:// or rediss:// in production.")
    elif not is_redis_reachable(redis_url):
        errors.append(
            "REDIS_URL is unreachable in production; silent fallback to memory:// is forbidden."
        )

    db_url = settings.effective_database_url
    if not db_url or db_url.startswith("sqlite:"):
        errors.append("DATABASE_URL must point to PostgreSQL in production (SQLite is forbidden).")

    if len(settings.effective_worker_api_key) < 24:
        errors.append("WORKER_API_KEY must be set (>= 24 chars) in production.")

    if len(settings.effective_auth_jwt_secret) < 32:
        errors.append("AUTH_JWT_SECRET must be explicitly set (>= 32 chars) in production.")

    if len(settings.effective_signed_url_secret) < 32:
        errors.append(
            "SIGNED_URL_SECRET or AUTH_JWT_SECRET (>= 32 chars) is required in production."
        )

    cors = settings.effective_cors_origins
    if not cors:
        errors.append("CORS_ORIGINS must specify explicit allowed origins in production.")
    elif "*" in cors and not _env_bool("ALLOW_WILDCARD_CORS", settings.ALLOW_WILDCARD_CORS):
        errors.append("CORS_ORIGINS cannot contain '*' in production.")

    if not settings.effective_gcp_project_id:
        errors.append("GCP_PROJECT_ID is required in production.")
    if not settings.effective_gcs_bucket:
        errors.append("GCS_BUCKET is required in production.")
    if not (
        settings.effective_google_api_key
        or settings.effective_vertex_access_token
        or settings.effective_google_application_credentials
    ):
        errors.append(
            "One Google Cloud credential (GOOGLE_API_KEY, VERTEX_ACCESS_TOKEN, "
            "or GOOGLE_APPLICATION_CREDENTIALS) is required in production."
        )

    if not settings.effective_stripe_secret_key:
        errors.append("STRIPE_SECRET_KEY is required in production.")
    if not settings.effective_stripe_webhook_secret:
        errors.append("STRIPE_WEBHOOK_SECRET is required in production.")

    if errors:
        raise RuntimeError(
            "Invalid production configuration; startup aborted:\n- " + "\n- ".join(errors)
        )


for _directory in (FIXTURES_DIR, STATIC_DIR, AUDIO_DIR, STORAGE_DIR):
    _directory.mkdir(parents=True, exist_ok=True)
