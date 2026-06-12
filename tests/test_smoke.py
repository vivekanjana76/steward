"""Smoke tests: the package imports and core scaffold invariants hold."""

from __future__ import annotations

from pathlib import Path

import pytest

from steward import __version__
from steward.config import Settings
from steward.llm.client import ModelRole, model_for


def test_package_version_present() -> None:
    assert isinstance(__version__, str) and __version__


def test_settings_safe_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Run in an empty dir with the relevant env vars cleared, so neither a
    # local `.env` nor the ambient environment can override the defaults.
    monkeypatch.chdir(tmp_path)
    for var in ("STEWARD_ENV", "STEWARD_DRY_RUN"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings()
    assert settings.env == "dev"
    # Dry-run must be the default — safety is opt-out, never opt-in (CLAUDE.md §5).
    assert settings.dry_run is True


def test_every_model_role_resolves() -> None:
    for role in ModelRole:
        assert model_for(role)
