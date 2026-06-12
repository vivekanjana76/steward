"""Triage: turn untrusted GitHub issues into typed, sanitized, classified models.

This package is the entry of the triage pipeline. It exposes the normalized
issue models, the ingestion adapter that maps raw GitHub payloads onto them, the
sanitization/injection-detection helpers applied to all untrusted text, the LLM
classifier that labels an issue as bug/feature/question, the embeddings-based
duplicate detector, and the policy-gated applier that turns outcomes into a
comment + labels on the real issue (dry-run by default).
"""

from __future__ import annotations

from steward.triage.apply import (
    AI_GENERATED_LABEL,
    DUPLICATE_LABEL,
    IssueWriter,
    TriageApplier,
    TriageProposal,
    build_triage_comment,
    build_triage_labels,
)
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
    "AI_GENERATED_LABEL",
    "DUPLICATE_LABEL",
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
    "IssueWriter",
    "NormalizedIssue",
    "ScoredIssue",
    "StoredIssue",
    "TriageApplier",
    "TriageDecision",
    "TriageProposal",
    "VectorStore",
    "VoyageEmbedder",
    "build_duplicate_detector",
    "build_embedder",
    "build_triage_comment",
    "build_triage_labels",
    "cosine_similarity",
    "detect_injection",
    "normalize_issue",
    "sanitize_text",
]
