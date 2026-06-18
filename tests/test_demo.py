"""Tests for `just demo` — the controlled, dry-run demo cycle (steward.demo).

The demo wires deterministic offline seams, so the whole cycle runs with no API
keys, no Docker, and no network — and must never mutate the outside world. These
tests pin that contract: the three seeded issues reach the expected dispositions,
a grounded fix is proposed for the bug, and every audit record is dry-run.
"""

from __future__ import annotations

from steward.demo import run_demo


def test_demo_runs_fully_offline_and_dry_run() -> None:
    result = run_demo()

    assert result.dry_run is True
    assert result.repo == "stewardbot/demo-shop"
    # Every gated decision is recorded, and none of them mutated the outside world.
    assert result.audit
    assert all("dry-run" in line for line in result.audit)
    assert all("LIVE" not in line for line in result.audit)


def test_demo_reaches_expected_dispositions() -> None:
    result = run_demo()
    by_number = {r.number: r for r in result.issues}

    # #1 bug → verified fix proposed as a draft PR (dry-run, pending approval),
    # after the multi-agent review council approved it (#55).
    bug = by_number[1]
    assert bug.triage == "bug"
    assert bug.pr_branch is not None
    assert "draft PR proposed" in bug.disposition
    assert bug.council is not None and bug.council.startswith("approve")

    # #2 is detected as a duplicate of the earlier bug — no fix attempted.
    dup = by_number[2]
    assert dup.triage == "duplicate"
    assert dup.duplicate_of == 1

    # #3 is too thin to act on — routed to needs-info, no action.
    thin = by_number[3]
    assert "needs-info" in thin.disposition


def test_demo_proposes_a_grounded_pr_body() -> None:
    result = run_demo()

    assert result.proposed_pr_body is not None
    body = result.proposed_pr_body
    # The proposed PR is clearly AI-authored, linked to the issue, and grounded
    # in real proof-test evidence (CLAUDE.md §1/§5).
    assert "Closes #1" in body
    assert "Steward (AI)" in body
    assert "Proof test" in body
