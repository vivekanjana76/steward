"""The graph's node functions and routing predicates.

Each node takes the current :class:`GraphState` and the injected
:class:`StewardDeps` and returns a **partial** state update (a dict keyed by
state fields) — never mutating the state in place. The routing predicates are
pure functions of the state that name the next node, so the control flow
(including backtracking and the VERIFY gate) is fully inspectable and testable.
"""

from __future__ import annotations

from steward.graph.capabilities import StewardDeps
from steward.graph.state import (
    GraphOutcome,
    GraphState,
    ReproVerdict,
    RouteTarget,
)
from steward.review.models import CouncilReview, ReviewContext, ReviewVerdict
from steward.triage.classify import IssueCategory

# Node names — referenced by both the builder's edges and the routers.
TRIAGE = "triage"
ROUTE = "route"
REPRODUCE = "reproduce"
HYPOTHESIZE = "hypothesize"
PATCH = "patch"
TEST = "test"
VERIFY = "verify"
COUNCIL = "council"
OPEN_PR = "open_pr"
GIVE_UP = "give_up"

StateUpdate = dict[str, object]


def triage_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """Classify the issue (bug / feature / question) via the real classifier."""
    decision = deps.classifier.classify(state.issue)
    return {
        "triage": decision,
        "notes": [f"triage: {decision.category.value} (confidence {decision.confidence:.2f})"],
    }


def route_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """Decide where the issue goes; set a terminal outcome for non-bug paths."""
    decision = state.triage
    assert decision is not None  # triage always runs first
    if decision.needs_info:
        return {
            "route": RouteTarget.NEEDS_INFO,
            "outcome": GraphOutcome.NEEDS_INFO,
            "notes": ["route: needs-info (low confidence) — not acting"],
        }
    if decision.category is IssueCategory.BUG:
        return {"route": RouteTarget.BUG, "notes": ["route: bug -> attempt reproduction"]}
    return {
        "route": RouteTarget.NON_BUG,
        "outcome": GraphOutcome.TRIAGED_NON_BUG,
        "notes": [f"route: {decision.category.value} — triage only, no fix attempted"],
    }


def reproduce_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """Attempt to reproduce the bug in the sandbox; record the grounded verdict."""
    outcome = deps.reproducer.reproduce(state.issue)
    update: StateUpdate = {
        "repro": outcome,
        "notes": [f"reproduce: {outcome.verdict.value} — {outcome.summary}"],
    }
    if outcome.verdict is ReproVerdict.COULD_NOT_REPRODUCE:
        update["outcome"] = GraphOutcome.COULD_NOT_REPRODUCE
    elif outcome.verdict is ReproVerdict.NEEDS_INFO:
        update["outcome"] = GraphOutcome.NEEDS_INFO
    return update


def hypothesize_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """Propose a cause hypothesis for the reproduced bug."""
    hypothesis = deps.hypothesizer.hypothesize(state)
    return {"hypothesis": hypothesis, "notes": [f"hypothesis: {hypothesis}"]}


def patch_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """Generate a candidate patch plus the proof test for the hypothesis."""
    patch = deps.patcher.propose(state)
    return {"patch": patch, "notes": ["patch: candidate diff + proof test generated"]}


def test_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """Run the proof test in the sandbox — the evidence VERIFY will check."""
    result = deps.tester.run_proof(state)
    attempts = state.attempts + 1
    verb = "passed" if result.passed else "failed"
    return {
        "test_result": result,
        "attempts": attempts,
        "notes": [f"proof test {verb} (attempt {attempts}/{state.max_attempts})"],
    }


def verify_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """The grounding gate: assert a fix only with real, passing test evidence.

    ``verified`` is true only when the bug was reproduced, a patch exists, and
    its proof test passed in the sandbox. Without all three, no "fixed" claim is
    made (CLAUDE.md §1/§3).
    """
    grounded = (
        state.test_result is not None
        and state.test_result.passed
        and state.repro is not None
        and state.repro.verdict is ReproVerdict.REPRODUCED
        and state.patch is not None
    )
    note = (
        "verify: fix grounded by passing proof test"
        if grounded
        else "verify: not grounded — withholding any 'fixed' claim"
    )
    return {"verified": grounded, "notes": [note]}


def council_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """The multi-agent review gate: a panel critiques the verified fix (#55).

    Runs after VERIFY, so a patch only reaches the council with a passing proof
    test. With no council configured the gate is a no-op approval, preserving the
    prior VERIFY→OPEN_PR behavior. A ``BLOCK`` is terminal (``REVIEW_REJECTED``);
    ``REQUEST_CHANGES`` backtracks to re-hypothesize while the retry budget lasts.
    """
    assert state.patch is not None  # guaranteed: VERIFY ran and grounded the fix
    if deps.council is None:
        review = CouncilReview.unanimous_approve("no review council configured; approving")
    else:
        context = ReviewContext(
            issue=state.issue,
            diff=state.patch.diff,
            proof_test=state.patch.proof_test,
            proof_test_path=state.patch.proof_test_path,
            hypothesis=state.hypothesis or "",
            repro_summary=state.repro.summary if state.repro else "",
            test_passed=state.test_result is not None and state.test_result.passed,
        )
        review = deps.council.review(context)
    update: StateUpdate = {
        "council_review": review,
        "notes": [f"council: {review.verdict.label} — {review.summary}"],
    }
    if review.verdict is ReviewVerdict.BLOCK:
        update["outcome"] = GraphOutcome.REVIEW_REJECTED
    return update


def open_pr_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """Open the draft PR for a verified fix (routed through policy in #16)."""
    pr = deps.pr_opener.open_draft(state)
    return {
        "pr": pr,
        "outcome": GraphOutcome.FIX_PROPOSED,
        "notes": [f"opened draft PR on branch {pr.branch}"],
    }


def give_up_node(state: GraphState, deps: StewardDeps) -> StateUpdate:
    """Terminal: retries exhausted or verification failed — no PR, honestly."""
    return {"outcome": GraphOutcome.GAVE_UP, "notes": ["gave up: no verified fix to propose"]}


# --- Routing predicates (pure functions of the state) ---------------------------


def route_after_triage(state: GraphState) -> str:
    """Only a bug routes onward; everything else is terminal after triage."""
    return REPRODUCE if state.route is RouteTarget.BUG else GIVE_UP_OR_END


def route_after_reproduce(state: GraphState) -> str:
    """A reproduced bug proceeds to hypothesize; otherwise the run is done."""
    reproduced = state.repro is not None and state.repro.verdict is ReproVerdict.REPRODUCED
    return HYPOTHESIZE if reproduced else GIVE_UP_OR_END


def route_after_test(state: GraphState) -> str:
    """Passing → verify; still failing with budget left → backtrack; else give up."""
    if state.test_result is not None and state.test_result.passed:
        return VERIFY
    if state.attempts < state.max_attempts:
        return HYPOTHESIZE
    return GIVE_UP


def route_after_verify(state: GraphState) -> str:
    """A grounded verification goes to the review council; an ungrounded one gives up."""
    return COUNCIL if state.verified else GIVE_UP


def route_after_council(state: GraphState) -> str:
    """Approve → open PR; request-changes → backtrack (budget permitting); block → end.

    A ``BLOCK`` is terminal and the council node already recorded
    ``REVIEW_REJECTED`` as the outcome, so it routes to END rather than the
    give-up node (which would overwrite that with ``GAVE_UP``). A
    ``REQUEST_CHANGES`` with no retry budget left honestly gives up.
    """
    review = state.council_review
    assert review is not None  # the council node always runs before this router
    if review.verdict is ReviewVerdict.APPROVE:
        return OPEN_PR
    if review.verdict is ReviewVerdict.BLOCK:
        return GIVE_UP_OR_END
    return HYPOTHESIZE if state.attempts < state.max_attempts else GIVE_UP


# A sentinel the builder maps to END for non-bug / not-reproduced terminal paths.
# These paths already set a descriptive `outcome`, so they end without a PR.
GIVE_UP_OR_END = "__end__"
