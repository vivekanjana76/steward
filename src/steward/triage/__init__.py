"""Triage: turn untrusted GitHub issues into typed, sanitized, classified models.

This package is the entry of the triage pipeline. It exposes the normalized
issue models, the ingestion adapter that maps raw GitHub payloads onto them, the
sanitization/injection-detection helpers applied to all untrusted text, the LLM
classifier that labels an issue as bug/feature/question, and the embeddings-based
duplicate detector.
"""

from __future__ import annotations

from steward.triage.classify import (
    Classification,
    IssueCategory,
    IssueClassifier,
    TriageDecision,
)
from steward.triage.dedup import (
    DuplicateCandidate,
    DuplicateDetector,
    DuplicateReport,
    Embedder,
    InMemoryVectorStore,
    ScoredIssue,
    StoredIssue,
    VectorStore,
    VoyageEmbedder,
    build_duplicate_detector,
    build_embedder,
    cosine_similarity,
)
from steward.triage.ingest import normalize_issue
from steward.triage.models import IssueComment, IssueState, NormalizedIssue
from steward.triage.sanitize import detect_injection, sanitize_text

__all__ = [
    "Classification",
    "DuplicateCandidate",
    "DuplicateDetector",
    "DuplicateReport",
    "Embedder",
    "InMemoryVectorStore",
    "IssueCategory",
    "IssueClassifier",
    "IssueComment",
    "IssueState",
    "NormalizedIssue",
    "ScoredIssue",
    "StoredIssue",
    "TriageDecision",
    "VectorStore",
    "VoyageEmbedder",
    "build_duplicate_detector",
    "build_embedder",
    "cosine_similarity",
    "detect_injection",
    "normalize_issue",
    "sanitize_text",
]
