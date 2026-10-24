"""Runtime configuration, loaded once from environment variables (12-factor)."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INQUIRA_", env_file=".env", extra="ignore")

    env: str = Field("development", description="development | production")
    # Signs session JWTs and derives the encryption key for stored secrets.
    # In production this MUST be set explicitly; we refuse to boot otherwise.
    secret_key: str = ""
    database_url: str = f"sqlite:///{REPO_ROOT / 'var' / 'inquira.db'}"
    data_dir: Path = REPO_ROOT / "var"
    demo_data_dir: Path = REPO_ROOT / "data" / "olist"

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    session_ttl_minutes: int = 60 * 12
    cookie_secure: bool | None = None  # defaults to True in production

    redis_url: str | None = None  # enables shared rate limiting across replicas
    login_rate_limit: str = "10/minute"
    ask_rate_limit: str = "30/minute"

    # Query guardrails
    max_result_rows: int = 500
    query_timeout_seconds: int = 30
    max_repair_attempts: int = 2

    # Optional env-provided LLM config. Takes precedence over the value stored via onboarding.
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure


def _resolve_secret(settings: Settings) -> None:
    if settings.secret_key:
        if len(settings.secret_key) < 32:
            raise RuntimeError("INQUIRA_SECRET_KEY must be at least 32 characters")
        return
    if settings.is_production:
        raise RuntimeError("INQUIRA_SECRET_KEY is required in production")
    # Development convenience: persist a random key so sessions and encrypted
    # settings survive restarts. Never used when a key is configured.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key_file = settings.data_dir / ".secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(48))
        key_file.chmod(0o600)
    settings.secret_key = key_file.read_text().strip()


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _resolve_secret(settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
