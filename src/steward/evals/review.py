"""Patch-review council evaluator (issue #55).

A council verdict (approve / request_changes / block) is a 3-way classification,
so it reuses the triage/repro metric machinery. The council is injected — the
live LLM-backed one when ``ANTHROPIC_API_KEY`` is set, the deterministic offline
council otherwise — so the gate runs keyless in CI yet measures the real council
when keys are present.
"""

from __future__ import annotations

from collections.abc import Sequence

from steward.evals.datasets import ReviewCase
from steward.evals.metrics import ClassificationMetrics, classification_metrics
from steward.review.council import PatchReviewer
from steward.review.models import ReviewContext

# The council label space, in increasing severity.
REVIEW_LABELS = ("approve", "request_changes", "block")


def run_review_eval(cases: Sequence[ReviewCase], council: PatchReviewer) -> ClassificationMetrics:
    """Score ``council`` over the labeled patch-review dataset."""
    pairs: list[tuple[str, str]] = []
    for case in cases:
        context = ReviewContext(
            diff=case.diff,
            proof_test=case.proof_test,
            test_passed=case.test_passed,
        )
        review = council.review(context)
        pairs.append((review.verdict.label, case.expected_verdict))
    return classification_metrics(pairs, REVIEW_LABELS)
