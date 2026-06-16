"""Triage evaluators: classification accuracy/F1 and duplicate precision/recall.

Each evaluator turns a labeled dataset + a capability into metrics. Capabilities
are injected (a ``classify`` callable, a built ``DuplicateDetector``), so the
same evaluators score the real model when keys are present and the offline
reference backends otherwise — and tests drive them with deterministic fakes.

Duplicate detection is scored the way it is *used*: an incoming issue is checked
against the **already-filed** backlog, so a duplicate claim must point to an
**earlier** issue. That matches reality (a new report duplicates an existing
one) and avoids penalizing a cluster's canonical for resembling its own later
duplicate.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pydantic import BaseModel

from steward.evals.datasets import ClassificationCase, DuplicateCase
from steward.evals.metrics import (
    BinaryMetrics,
    ClassificationMetrics,
    binary_metrics,
    classification_metrics,
)
from steward.triage.classify import TriageDecision
from steward.triage.dedup import DuplicateDetector
from steward.triage.ingest import normalize_issue
from steward.triage.models import NormalizedIssue

# The label space for triage classification (needs-info is a routing label).
TRIAGE_LABELS = ("bug", "feature", "question", "needs_info")

Classify = Callable[[NormalizedIssue], TriageDecision]


class ClassificationEvalResult(BaseModel):
    """Classification metrics plus the injection-surfacing recall."""

    model_config = {"frozen": True}

    metrics: ClassificationMetrics
    injection_recall: float
    injection_cases: int


def issue_from_case(number: int, title: str, body: str) -> NormalizedIssue:
    """Build a sanitized :class:`NormalizedIssue` from raw case text (ingestion).

    Running real ingestion means the same sanitization and prompt-injection
    detection the product uses is exercised by the eval.
    """
    return normalize_issue(
        {
            "number": number,
            "title": title,
            "body": body,
            "state": "open",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    )


def _expected_label(case: ClassificationCase) -> str:
    return "needs_info" if case.expected_needs_info else (case.expected_category or "")


def _predicted_label(decision: TriageDecision) -> str:
    return "needs_info" if decision.needs_info else decision.category.value


def run_classification_eval(
    cases: Sequence[ClassificationCase], classify: Classify
) -> ClassificationEvalResult:
    """Score ``classify`` over the classification dataset."""
    pairs: list[tuple[str, str]] = []
    injection_total = 0
    injection_hit = 0
    for index, case in enumerate(cases):
        issue = issue_from_case(index + 1, case.title, case.body)
        decision = classify(issue)
        pairs.append((_predicted_label(decision), _expected_label(case)))
        if case.expected_injection_signal is not None:
            injection_total += 1
            if case.expected_injection_signal in issue.injection_signals:
                injection_hit += 1
    metrics = classification_metrics(pairs, TRIAGE_LABELS)
    injection_recall = injection_hit / injection_total if injection_total else 1.0
    return ClassificationEvalResult(
        metrics=metrics, injection_recall=injection_recall, injection_cases=injection_total
    )


def run_dedup_eval(cases: Sequence[DuplicateCase], detector: DuplicateDetector) -> BinaryMetrics:
    """Index the corpus and score duplicate retrieval (earlier-issue framing)."""
    issues = [issue_from_case(c.number, c.title, c.body) for c in cases]
    detector.index(issues)

    decisions: list[tuple[bool, bool]] = []
    for case, issue in zip(cases, issues, strict=True):
        report = detector.find_duplicates(issue)
        earlier = [c for c in report.candidates if c.issue_number < case.number]
        predicted = earlier[0].issue_number if earlier else None
        actual_positive = case.duplicate_of is not None
        # A correct claim points to the labeled canonical; a claim on a unique
        # issue is a false positive.
        predicted_positive = predicted is not None and (
            not actual_positive or predicted == case.duplicate_of
        )
        decisions.append((predicted_positive, actual_positive))
    return binary_metrics(decisions)
