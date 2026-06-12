"""Normalized, validated Pydantic models for issues entering triage.

These are the typed contract every downstream node (classify, dedup, reproduce)
depends on (CLAUDE.md §4). They are intentionally decoupled from the GitHub API
payload shape — :mod:`steward.triage.ingest` maps raw payloads onto these — so a
different source (or a fixture) produces the same model.

Models are frozen: a normalized issue is an immutable snapshot. Text fields hold
**sanitized** content; ``injection_signals`` records any prompt-injection
heuristics that fired during ingestion, so downstream logic can stay grounded
and cautious (CLAUDE.md §5).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class IssueState(StrEnum):
    """Lifecycle state of an issue."""

    OPEN = "open"
    CLOSED = "closed"


class IssueComment(BaseModel):
    """A single comment on an issue, with sanitized body text."""

    model_config = ConfigDict(frozen=True)

    comment_id: int
    author: str | None = None
    body: str = ""
    created_at: datetime


class NormalizedIssue(BaseModel):
    """A source-agnostic, validated snapshot of an issue ready for triage.

    All free text (``title``, ``body``, comment bodies) is sanitized at
    ingestion. ``injection_signals`` is the de-duplicated set of prompt-injection
    heuristics detected across the title, body, and comments — empty when none
    fired.
    """

    model_config = ConfigDict(frozen=True)

    number: int
    title: str = ""
    body: str = ""
    author: str | None = None
    state: IssueState
    labels: tuple[str, ...] = ()
    created_at: datetime
    updated_at: datetime
    comments: tuple[IssueComment, ...] = ()
    injection_signals: tuple[str, ...] = Field(default=())

    @property
    def has_injection_signals(self) -> bool:
        """True if any prompt-injection heuristic fired during ingestion."""
        return bool(self.injection_signals)
