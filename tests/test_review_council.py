"""Tests for the multi-agent reviewer council (issue #55).

Three layers, all deterministic and keyless:

* **aggregation** — the supervisor folds findings worst-verdict-wins;
* **offline reviewers** — each specialist's grounded heuristic on a diff;
* **LLM reviewer** — the real structured (forced-tool-use) path against a stubbed
  Anthropic SDK, so an agent reviewer is exercised without the network.

The graph integration (council gating the PR, backtracking on request-changes,
terminal block) is covered in ``test_graph.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from steward.llm.client import ModelClient
from steward.review import (
    CouncilReview,
    LLMReviewer,
    ReviewContext,
    ReviewCouncil,
    ReviewDimension,
    ReviewFinding,
    ReviewVerdict,
    build_offline_council,
)
from steward.review.offline import (
    OfflineCorrectnessReviewer,
    OfflineSecurityReviewer,
    OfflineTestQualityReviewer,
)
from steward.triage.models import IssueState, NormalizedIssue

# --- fixtures -----------------------------------------------------------------

_CLEAN_DIFF = "--- a/shop/checkout.py\n+++ b/shop/checkout.py\n+    return subtotal - discount\n"
_GOOD_TEST = "def test_discount():\n    assert apply_discount(100, 10) == 90\n"


def _ctx(diff: str = _CLEAN_DIFF, *, proof_test: str = _GOOD_TEST, test_passed: bool = True):
    return ReviewContext(diff=diff, proof_test=proof_test, test_passed=test_passed)


def _finding(dimension: str, verdict: ReviewVerdict) -> ReviewFinding:
    return ReviewFinding(dimension=dimension, verdict=verdict, rationale="because", citation="c")


# --- aggregation (the supervisor) ---------------------------------------------


def test_aggregate_empty_is_approve() -> None:
    review = CouncilReview.aggregate([])
    assert review.verdict is ReviewVerdict.APPROVE
    assert review.approved


def test_aggregate_worst_verdict_wins() -> None:
    findings = [
        _finding("correctness", ReviewVerdict.APPROVE),
        _finding("test_quality", ReviewVerdict.REQUEST_CHANGES),
        _finding("security", ReviewVerdict.BLOCK),
    ]
    review = CouncilReview.aggregate(findings)
    assert review.verdict is ReviewVerdict.BLOCK
    assert not review.approved
    assert "security" in review.summary
    assert len(review.findings) == 3


def test_aggregate_all_approve() -> None:
    review = CouncilReview.aggregate([_finding("correctness", ReviewVerdict.APPROVE)])
    assert review.approved
    assert "approved" in review.summary


# --- offline specialists ------------------------------------------------------


def test_security_blocks_sink_with_citation() -> None:
    finding = OfflineSecurityReviewer().review(_ctx("+++ b/x\n+    os.system(cmd)\n"))
    assert finding.verdict is ReviewVerdict.BLOCK
    assert finding.dimension == ReviewDimension.SECURITY
    assert "os.system" in finding.citation


def test_security_blocks_hardcoded_secret() -> None:
    finding = OfflineSecurityReviewer().review(_ctx('+++ b/x\n+    api_key = "sk-live-123"\n'))
    assert finding.verdict is ReviewVerdict.BLOCK


def test_security_approves_clean_diff() -> None:
    assert OfflineSecurityReviewer().review(_ctx()).verdict is ReviewVerdict.APPROVE


def test_correctness_requests_changes_on_empty_diff() -> None:
    # A diff that only adds a comment changes no code.
    finding = OfflineCorrectnessReviewer().review(_ctx("+++ b/x\n+    # just a note\n"))
    assert finding.verdict is ReviewVerdict.REQUEST_CHANGES


def test_correctness_flags_debug_leftovers() -> None:
    finding = OfflineCorrectnessReviewer().review(_ctx("+++ b/x\n+    print(subtotal)\n"))
    assert finding.verdict is ReviewVerdict.REQUEST_CHANGES
    assert "print" in finding.citation


def test_test_quality_requires_a_passing_assertion() -> None:
    reviewer = OfflineTestQualityReviewer()
    assert reviewer.review(_ctx(proof_test="")).verdict is ReviewVerdict.REQUEST_CHANGES
    assert reviewer.review(_ctx(proof_test="x = 1\n")).verdict is ReviewVerdict.REQUEST_CHANGES
    assert reviewer.review(_ctx(test_passed=False)).verdict is ReviewVerdict.REQUEST_CHANGES
    assert reviewer.review(_ctx()).verdict is ReviewVerdict.APPROVE


def test_offline_council_approves_a_clean_fix() -> None:
    review = build_offline_council().review(_ctx())
    assert review.approved
    assert review.findings  # every seat reported


def test_offline_council_blocks_dangerous_fix() -> None:
    review = build_offline_council().review(_ctx("+++ b/x\n+    eval(payload)\n"))
    assert review.verdict is ReviewVerdict.BLOCK


# --- the LLM-backed reviewer (real structured path, stubbed SDK) --------------


def _tool_response(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        model="stub-model",
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=30, output_tokens=10),
        content=[SimpleNamespace(type="tool_use", name="format_response", input=payload)],
    )


class _StubMessages:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _StubAnthropic:
    def __init__(self, response: Any) -> None:
        self.messages = _StubMessages(response)


def test_llm_reviewer_maps_structured_reply_to_finding() -> None:
    stub = _StubAnthropic(
        _tool_response({"verdict": 2, "rationale": "shells out", "citation": "os.system(cmd)"})
    )
    client = ModelClient(client=stub)
    reviewer = LLMReviewer(ReviewDimension.SECURITY, client)

    finding = reviewer.review(_ctx("+++ b/x\n+    os.system(cmd)\n"))

    assert finding.dimension == ReviewDimension.SECURITY
    assert finding.verdict is ReviewVerdict.BLOCK
    assert finding.citation == "os.system(cmd)"
    # Forced tool use was requested, and the patch was presented as fenced DATA.
    call = stub.messages.calls[0]
    assert call["tool_choice"]["type"] == "tool"
    assert "<diff>" in call["messages"][0]["content"]


def test_llm_council_runs_each_seat() -> None:
    stub = _StubAnthropic(_tool_response({"verdict": 0, "rationale": "fine"}))
    council = ReviewCouncil(
        [
            LLMReviewer(ReviewDimension.CORRECTNESS, ModelClient(client=stub)),
            LLMReviewer(ReviewDimension.SECURITY, ModelClient(client=stub)),
        ]
    )
    review = council.review(_ctx())
    assert review.approved
    assert {f.dimension for f in review.findings} == {"correctness", "security"}


def _issue() -> NormalizedIssue:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    return NormalizedIssue(
        number=1, title="t", body="b", state=IssueState.OPEN, created_at=now, updated_at=now
    )


def test_review_context_carries_optional_issue() -> None:
    ctx = ReviewContext(issue=_issue(), diff=_CLEAN_DIFF)
    assert ctx.issue is not None and ctx.issue.number == 1
