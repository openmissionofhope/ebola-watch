"""Runtime configuration.

All configuration comes from environment variables (prefix ``EW_``) or a local
``.env`` file. Secrets are never hard-coded; production refuses to start with
development defaults (see :func:`Settings.validate_for_production`).
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEV_SECRET = "dev-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EW_", env_file=".env", extra="ignore")

    env: str = Field("development", description="development | test | production")
    # "server": the API serves the dashboard (PostgreSQL in production).
    # "static": a scheduled batch job publishes a static snapshot; a single
    # writer, so SQLite is acceptable in production.
    deployment: str = Field("server", description="server | static")
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'var' / 'ebolawatch.db'}"
    data_dir: Path = PROJECT_ROOT / "data"
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"

    # Secrets. ``secret_key`` peppers API-key hashes; ``pseudonym_salt`` keys the
    # HMAC used to pseudonymise social-media authors (never stored in clear).
    secret_key: str = DEV_SECRET
    pseudonym_salt: str = DEV_SECRET

    # Outbound HTTP
    user_agent: str = "EbolaWatch/0.1 (Open Mission of Hope; +https://openmissionofhope.org)"
    http_timeout_s: float = 30.0
    http_max_retries: int = 3

    # Sources. Some upstream producers attach conditions (courtesy requests,
    # pre-publication contact). Those connectors only run when the operator
    # lists them here after reviewing the terms in docs/DATA_SOURCES.md.
    source_acknowledgements: Annotated[list[str], NoDecode] = Field(default_factory=list)
    disabled_sources: Annotated[list[str], NoDecode] = Field(default_factory=list)
    reliefweb_appname: str | None = None
    youtube_api_key: str | None = None
    x_bearer_token: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    promed_feed_url: str | None = None
    rss_feeds: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Optional machine translation for reviewers (sends PII-redacted text to Anthropic).
    enable_llm_translation: bool = False
    llm_model: str = "claude-opus-5-5"

    # Scope: the epidemic declared in the Democratic Republic of the Congo on
    # 15 May 2026. Outbreaks declared earlier (WHO's bulletin archive goes back
    # to 2001) stay in the database but are neither assessed nor published.
    epidemic_start: date = date(2026, 5, 15)

    # Privacy / publication controls
    min_public_cell_count: int = 5
    min_public_subnational_population: int = 50_000
    public_max_admin_level: int = 1
    raw_content_retention_days: int = 30
    signal_retention_days: int = 365
    query_guard_window_s: int = 3600
    query_guard_max_distinct_filters: int = 30

    # API
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    rate_limit_per_minute: int = 120
    export_rate_limit_per_hour: int = 20
    trust_forwarded_for: bool = False

    # Scheduler intervals (seconds)
    ingest_interval_s: int = 6 * 3600
    analysis_interval_s: int = 6 * 3600
    retention_interval_s: int = 24 * 3600

    @field_validator("source_acknowledgements", "disabled_sources", "rss_feeds", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate_for_production(self) -> None:
        if not self.is_production:
            return
        problems = []
        if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
            problems.append("EW_SECRET_KEY must be set to a random value of at least 32 characters")
        if self.pseudonym_salt == DEV_SECRET or len(self.pseudonym_salt) < 32:
            problems.append("EW_PSEUDONYM_SALT must be set to a random value of at least 32 characters")
        if self.database_url.startswith("sqlite") and self.deployment != "static":
            problems.append("Production server deployments must use PostgreSQL (EW_DATABASE_URL)")
        if problems:
            raise RuntimeError("Refusing to start in production: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
