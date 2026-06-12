"""Triage: turn untrusted GitHub issues into typed, sanitized Steward models.

This package is the entry of the triage pipeline. It exposes the normalized
issue models, the ingestion adapter that maps raw GitHub payloads onto them, and
the sanitization/injection-detection helpers applied to all untrusted text.
"""

from __future__ import annotations

from steward.triage.ingest import normalize_issue
from steward.triage.models import IssueComment, IssueState, NormalizedIssue
from steward.triage.sanitize import detect_injection, sanitize_text

__all__ = [
    "IssueComment",
    "IssueState",
    "NormalizedIssue",
    "detect_injection",
    "normalize_issue",
    "sanitize_text",
]
