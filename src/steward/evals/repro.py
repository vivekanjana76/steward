"""Reproduction-verdict evaluator (issue #21).

A repro verdict (reproduced / could-not-reproduce / needs-info) is a 3-way
classification, so it reuses the same metric machinery as triage. The reproducer
is injected — the real one (sandbox-backed) when available, the deterministic
offline reproducer otherwise, and a fake in tests.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from steward.evals.datasets import ReproCase
from steward.evals.metrics import ClassificationMetrics, classification_metrics
from steward.evals.triage import issue_from_case
from steward.graph.state import ReproOutcome
from steward.triage.models import NormalizedIssue

# The repro verdict label space.
REPRO_LABELS = ("reproduced", "could_not_reproduce", "needs_info")

Reproduce = Callable[[NormalizedIssue], ReproOutcome]


def run_repro_eval(cases: Sequence[ReproCase], reproduce: Reproduce) -> ClassificationMetrics:
    """Score ``reproduce`` over the labeled reproduction dataset."""
    pairs: list[tuple[str, str]] = []
    for index, case in enumerate(cases):
        issue = issue_from_case(index + 1, case.title, case.body)
        outcome = reproduce(issue)
        pairs.append((outcome.verdict.value, case.expected_verdict))
    return classification_metrics(pairs, REPRO_LABELS)
