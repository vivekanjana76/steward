"""Central, validated configuration for Steward.

Values load from environment variables and an optional local ``.env`` file.
This is the single source of truth for runtime configuration; never commit real
secrets (see ``.env.example`` for the required keys and ``CLAUDE.md`` §12).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide settings.

    Secret-bearing fields are marked ``repr=False`` so they never leak into logs
    or tracebacks. Conventional, unprefixed names are used for third-party
    secrets (e.g. ``ANTHROPIC_API_KEY``); Steward-specific knobs use the
    ``STEWARD_`` prefix.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = Field(default="dev", validation_alias="STEWARD_ENV")
    # Safety default: no world-mutating action executes live until explicitly
    # opted in. New action types ship in dry-run (CLAUDE.md §5).
    dry_run: bool = Field(default=True, validation_alias="STEWARD_DRY_RUN")
    # Per-kind live opt-in: a comma-separated list of ActionKind values that may
    # execute live once dry_run is off. Empty means nothing runs live even then.
    live_actions: str = Field(default="", validation_alias="STEWARD_LIVE_ACTIONS")

    anthropic_api_key: str | None = Field(
        default=None, validation_alias="ANTHROPIC_API_KEY", repr=False
    )

    # Voyage AI — embeddings for duplicate-issue detection (required for live
    # dedup; see steward.triage.dedup and ADR-0002).
    voyage_api_key: str | None = Field(default=None, validation_alias="VOYAGE_API_KEY", repr=False)

    langfuse_public_key: str | None = Field(
        default=None, validation_alias="LANGFUSE_PUBLIC_KEY", repr=False
    )
    langfuse_secret_key: str | None = Field(
        default=None, validation_alias="LANGFUSE_SECRET_KEY", repr=False
    )
    langfuse_host: str | None = Field(default=None, validation_alias="LANGFUSE_HOST")

    github_token: str | None = Field(default=None, validation_alias="GITHUB_TOKEN", repr=False)
    # Target repository, ``owner/name``. Steward only ever acts on a repo it
    # owns/controls (CLAUDE.md §5).
    github_repo: str | None = Field(default=None, validation_alias="STEWARD_GITHUB_REPO")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton."""
    return Settings()
