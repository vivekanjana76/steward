"""Tests for the eval suite: metrics, datasets, evaluators, report, and gate (#20/#23).

The metric math and the baseline gate are pure and unit-tested; the evaluators
are run against the real committed datasets with the deterministic **offline**
backends, so this also pins that the harness end-to-end produces a clean,
reproducible baseline with no keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from steward.config import Settings
from steward.evals.datasets import (
    ClassificationCase,
    load_classification_cases,
    load_duplicate_cases,
    load_repro_cases,
)
from steward.evals.metrics import binary_metrics, classification_metrics
from steward.evals.offline import HashingTfEmbedder, OfflineClassifier, OfflineReproducer
from steward.evals.report import EvalReport, check_regressions, load_baseline
from steward.evals.repro import REPRO_LABELS, run_repro_eval
from steward.evals.run import build_report
from steward.evals.triage import (
    TRIAGE_LABELS,
    run_classification_eval,
    run_dedup_eval,
)
from steward.triage.dedup import DuplicateDetector, InMemoryVectorStore

# --- metrics ------------------------------------------------------------------


def test_classification_metrics_perfect() -> None:
    pairs = [("bug", "bug"), ("feature", "feature"), ("question", "question")]
    m = classification_metrics(pairs, TRIAGE_LABELS)
    assert m.accuracy == 1.0
    assert m.macro_f1 == 1.0
    assert m.per_class["needs_info"].support == 0  # absent label still scored


def test_classification_metrics_with_an_error() -> None:
    pairs = [("bug", "bug"), ("bug", "feature")]  # one wrong
    m = classification_metrics(pairs, ("bug", "feature"))
    assert m.accuracy == 0.5
    assert m.per_class["feature"].recall == 0.0


def test_binary_metrics_counts() -> None:
    decisions = [(True, True), (True, False), (False, True), (False, False)]
    b = binary_metrics(decisions)
    assert (b.tp, b.fp, b.fn, b.tn) == (1, 1, 1, 1)
    assert b.precision == 0.5
    assert b.recall == 0.5


# --- datasets -----------------------------------------------------------------


def test_datasets_load_and_validate() -> None:
    cls = load_classification_cases()
    dup = load_duplicate_cases()
    assert len(cls) >= 7
    assert len(dup) >= 6
    assert any(c.expected_needs_info for c in cls)
    assert any(c.duplicate_of is not None for c in dup)


def test_dataset_rejects_unknown_field() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic extra=forbid
        ClassificationCase.model_validate({"id": "x", "title": "t", "surprise": 1})


# --- evaluators (offline backends on the real datasets) -----------------------


def test_offline_classifier_scores_perfectly_on_dataset() -> None:
    result = run_classification_eval(load_classification_cases(), OfflineClassifier().classify)
    assert result.metrics.macro_f1 == 1.0
    assert result.injection_recall == 1.0
    assert result.injection_cases == 1


def test_offline_dedup_scores_perfectly_on_dataset() -> None:
    detector = DuplicateDetector(HashingTfEmbedder(), InMemoryVectorStore(), threshold=0.25)
    metrics = run_dedup_eval(load_duplicate_cases(), detector)
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.fp == 0


def test_classification_eval_reflects_a_wrong_prediction() -> None:
    from steward.triage.classify import IssueCategory, TriageDecision
    from steward.triage.models import NormalizedIssue

    def always_feature(issue: NormalizedIssue) -> TriageDecision:
        return TriageDecision(
            category=IssueCategory.FEATURE, confidence=0.9, rationale="x", needs_info=False
        )

    cases = [ClassificationCase(id="a", title="crash", body="segfault", expected_category="bug")]
    result = run_classification_eval(cases, always_feature)
    assert result.metrics.accuracy == 0.0


# --- reproduction verdict -----------------------------------------------------


def test_repro_dataset_covers_every_verdict() -> None:
    verdicts = {c.expected_verdict for c in load_repro_cases()}
    assert verdicts == set(REPRO_LABELS)


def test_offline_reproducer_scores_perfectly_on_dataset() -> None:
    metrics = run_repro_eval(load_repro_cases(), OfflineReproducer().reproduce)
    assert metrics.accuracy == 1.0
    assert metrics.macro_f1 == 1.0


def test_repro_eval_reflects_a_wrong_verdict() -> None:
    from steward.evals.datasets import ReproCase
    from steward.graph.state import ReproOutcome, ReproVerdict
    from steward.triage.models import NormalizedIssue

    def always_reproduced(issue: NormalizedIssue) -> ReproOutcome:
        return ReproOutcome(verdict=ReproVerdict.REPRODUCED, summary="x")

    cases = [ReproCase(id="a", title="t", body="b", expected_verdict="needs_info")]
    assert run_repro_eval(cases, always_reproduced).accuracy == 0.0


# --- report + gate ------------------------------------------------------------


def test_build_report_offline_is_clean() -> None:
    report = build_report(Settings(_env_file=None))  # type: ignore[call-arg]
    assert report.backend == "offline"
    assert report.metrics["triage_f1"] == 1.0
    assert report.metrics["dedup_recall"] == 1.0
    assert report.metrics["repro_accuracy"] == 1.0


def test_report_round_trips(tmp_path: Path) -> None:
    report = EvalReport.create(
        backend="offline", subset="t", metrics={"triage_f1": 0.9}, details={}
    )
    path = tmp_path / "report.json"
    report.write(path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["metrics"]["triage_f1"] == 0.9


def test_gate_passes_when_metrics_meet_baseline() -> None:
    assert check_regressions({"a": 1.0, "b": 0.9}, {"a": 1.0, "b": 0.8}) == []


def test_gate_flags_a_drop() -> None:
    regs = check_regressions({"a": 0.7}, {"a": 0.9})
    assert len(regs) == 1
    assert regs[0].metric == "a"


def test_gate_flags_a_missing_metric() -> None:
    regs = check_regressions({}, {"triage_f1": 0.8})
    assert regs[0].metric == "triage_f1"


def test_committed_baseline_is_not_below_current_offline_run() -> None:
    # The committed baseline must be achievable by the offline harness, so CI
    # (which has no keys) stays green.
    report = build_report(Settings(_env_file=None))  # type: ignore[call-arg]
    assert check_regressions(report.metrics, load_baseline()) == []
