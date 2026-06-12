"""Triage: turn untrusted GitHub issues into typed, sanitized, classified models.

This package is the entry of the triage pipeline. It exposes the normalized
issue models, the ingestion adapter that maps raw GitHub payloads onto them, the
sanitization/injection-detection helpers applied to all untrusted text, and the
LLM classifier that labels an issue as bug/feature/question.
"""

from __future__ import annotations

from steward.triage.classify import (
    Classification,
    IssueCategory,
    IssueClassifier,
    TriageDecision,
)
from steward.triage.ingest import normalize_issue
from steward.triage.models import IssueComment, IssueState, NormalizedIssue
from steward.triage.sanitize import detect_injection, sanitize_text

__all__ = [
    "Classification",
    "IssueCategory",
    "IssueClassifier",
    "IssueComment",
    "IssueState",
    "NormalizedIssue",
    "TriageDecision",
    "detect_injection",
    "normalize_issue",
    "sanitize_text",
]
