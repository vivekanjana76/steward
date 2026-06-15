"""Integration tests for the agent graph (issue #14).

The full graph runs on a fixed fixture issue with every capability stubbed by a
deterministic fake — no model, no Docker, no network — so the *control flow*
(routing, backtracking, the VERIFY gate) is asserted exactly. Counters on the
fakes prove backtracking really re-enters hypothesize rather than pushing
forward, and that the graph never claims a fix without passing test evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from steward.graph import (
    GraphOutcome,
    OpenedPR,
    ProposedPatch,
    ReproOutcome,
    ReproVerdict,
    StewardDeps,
    build_graph,
    run_issue,
)
from steward.graph.state import GraphState
from steward.sandbox import SandboxResult
from steward.triage.classify import IssueCategory, TriageDecision
from steward.triage.models import IssueState, NormalizedIssue


def _issue(number: int = 1) -> NormalizedIssue:
    now = datetime.now(UTC)
    return NormalizedIssue(
        number=number,
        title="Checkout total ignores discount",
        body="Applying a code does not reduce the total.",
        state=IssueState.OPEN,
        created_at=now,
        updated_at=now,
    )


def _sandbox(passed: bool) -> SandboxResult:
    return SandboxResult(
        passed=passed,
        exit_code=0 if passed else 1,
        timed_out=False,
        duration_s=0.1,
        stdout="ok" if passed else "AssertionError",
        stderr="",
        image="python:3.12-slim",
        command="pytest -q",
    )


class FakeClassifier:
    def __init__(self, category: IssueCategory, confidence: float = 0.9, needs_info: bool = False):
        self._decision = TriageDecision(
            category=category, confidence=confidence, rationale="fixture", needs_info=needs_info
        )

    def classify(self, issue: NormalizedIssue) -> TriageDecision:
        return self._decision


class FakeReproducer:
    def __init__(self, verdict: ReproVerdict):
        self._verdict = verdict

    def reproduce(self, issue: NormalizedIssue) -> ReproOutcome:
        evidence = _sandbox(False) if self._verdict is ReproVerdict.REPRODUCED else None
        return ReproOutcome(verdict=self._verdict, summary="fixture", evidence=evidence)


class CountingHypothesizer:
    def __init__(self) -> None:
        self.calls = 0

    def hypothesize(self, state: GraphState) -> str:
        self.calls += 1
        return f"hypothesis #{self.calls}"


class FakePatcher:
    def propose(self, state: GraphState) -> ProposedPatch:
        return ProposedPatch(diff="--- a/x\n+++ b/x", proof_test="def test_fix(): ...")


class ScriptedTester:
    """Returns canned pass/fail outcomes in order, one per test cycle."""

    def __init__(self, *outcomes: bool):
        self._outcomes = list(outcomes)
        self.calls = 0

    def run_proof(self, state: GraphState) -> SandboxResult:
        passed = self._outcomes[self.calls]
        self.calls += 1
        return _sandbox(passed)


class RecordingPROpener:
    def __init__(self) -> None:
        self.opened = False

    def open_draft(self, state: GraphState) -> OpenedPR:
        self.opened = True
        return OpenedPR(branch=f"fix/issue-{state.issue.number}", title="Fix", number=7, url="u")


def _deps(
    *,
    category: IssueCategory = IssueCategory.BUG,
    needs_info: bool = False,
    repro: ReproVerdict = ReproVerdict.REPRODUCED,
    test_outcomes: tuple[bool, ...] = (True,),
    hypothesizer: CountingHypothesizer | None = None,
    pr_opener: RecordingPROpener | None = None,
) -> StewardDeps:
    return StewardDeps(
        classifier=FakeClassifier(category, needs_info=needs_info),
        reproducer=FakeReproducer(repro),
        hypothesizer=hypothesizer or CountingHypothesizer(),
        patcher=FakePatcher(),
        tester=ScriptedTester(*test_outcomes),
        pr_opener=pr_opener or RecordingPROpener(),
    )


def _run(deps: StewardDeps, *, max_attempts: int = 2) -> GraphState:
    graph = build_graph(deps)
    return run_issue(graph, _issue(), trace_id="t", thread_id="th", max_attempts=max_attempts)


def test_happy_path_opens_pr() -> None:
    pr = RecordingPROpener()
    state = _run(_deps(test_outcomes=(True,), pr_opener=pr))
    assert state.outcome is GraphOutcome.FIX_PROPOSED
    assert state.verified is True
    assert state.pr is not None and state.pr.branch == "fix/issue-1"
    assert pr.opened is True


def test_non_bug_ends_after_triage() -> None:
    pr = RecordingPROpener()
    state = _run(_deps(category=IssueCategory.FEATURE, pr_opener=pr))
    assert state.outcome is GraphOutcome.TRIAGED_NON_BUG
    assert state.repro is None  # never attempted reproduction
    assert pr.opened is False


def test_low_confidence_routes_to_needs_info() -> None:
    state = _run(_deps(needs_info=True))
    assert state.outcome is GraphOutcome.NEEDS_INFO
    assert state.repro is None


def test_could_not_reproduce_ends_without_fix() -> None:
    hypo = CountingHypothesizer()
    pr = RecordingPROpener()
    state = _run(_deps(repro=ReproVerdict.COULD_NOT_REPRODUCE, hypothesizer=hypo, pr_opener=pr))
    assert state.outcome is GraphOutcome.COULD_NOT_REPRODUCE
    assert hypo.calls == 0  # never tried to fix what it couldn't reproduce
    assert pr.opened is False


def test_failing_test_backtracks_then_succeeds() -> None:
    hypo = CountingHypothesizer()
    pr = RecordingPROpener()
    # First proof test fails, second passes — the graph must loop back once.
    state = _run(
        _deps(test_outcomes=(False, True), hypothesizer=hypo, pr_opener=pr), max_attempts=3
    )
    assert state.outcome is GraphOutcome.FIX_PROPOSED
    assert state.verified is True
    assert hypo.calls == 2  # re-hypothesized after the first failure
    assert state.attempts == 2
    assert pr.opened is True


def test_exhausting_retries_gives_up_without_pr() -> None:
    pr = RecordingPROpener()
    state = _run(_deps(test_outcomes=(False, False), pr_opener=pr), max_attempts=2)
    assert state.outcome is GraphOutcome.GAVE_UP
    assert state.verified is False
    assert state.attempts == 2
    assert pr.opened is False


def test_verify_withholds_claim_without_passing_evidence() -> None:
    # Even if everything else ran, a non-passing proof test must not verify.
    state = _run(_deps(test_outcomes=(False, False)), max_attempts=2)
    assert state.verified is False
    assert state.pr is None


def test_notes_trail_is_accumulated() -> None:
    state = _run(_deps(test_outcomes=(True,)))
    joined = " | ".join(state.notes)
    assert "triage:" in joined
    assert "reproduce:" in joined
    assert "proof test passed" in joined
    assert "verify:" in joined


def test_checkpointer_persists_state_for_thread() -> None:
    graph = build_graph(_deps(test_outcomes=(True,)))
    graph.invoke(
        {"issue": _issue(), "trace_id": "t", "max_attempts": 2},
        config={"configurable": {"thread_id": "persist-1"}},
    )
    snapshot = graph.get_state({"configurable": {"thread_id": "persist-1"}})
    assert snapshot.values["outcome"] == GraphOutcome.FIX_PROPOSED


@pytest.mark.parametrize("category", [IssueCategory.FEATURE, IssueCategory.QUESTION])
def test_only_bugs_reach_reproduction(category: IssueCategory) -> None:
    state = _run(_deps(category=category))
    assert state.repro is None
    assert state.outcome is GraphOutcome.TRIAGED_NON_BUG
