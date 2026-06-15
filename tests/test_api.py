"""Tests for the FastAPI service (issue #42).

The app is exercised through Starlette's ``TestClient`` (ASGI, no live socket)
with an injected :class:`ApiState` built on an in-memory audit log + approval
queue, so every test is deterministic and offline. The focus is the contract
the dashboard depends on and the preservation of policy invariants:
approve/reject go through the queue, denials/refusals are visible, and bad
transitions surface as the right HTTP status — never a silent no-op.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from steward.api.app import create_app
from steward.api.seed import seed_demo
from steward.api.state import ApiState, get_state, load_scorecard
from steward.config import Settings
from steward.policy.approvals import ApprovalQueue
from steward.policy.audit import InMemoryAuditLog
from steward.policy.engine import Action, ActionKind, PolicyDecision, classify

TARGET = "stewardbot/demo-shop"


def _settings(**env: str) -> Settings:
    base = {"STEWARD_GITHUB_REPO": TARGET, "STEWARD_ENV": "test"}
    base.update(env)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def _build(*, seed: bool = False, report_path: Path | None = None) -> tuple[TestClient, ApiState]:
    settings = _settings()
    audit = InMemoryAuditLog()
    state = ApiState(
        settings=settings,
        audit_log=audit,
        approval_queue=ApprovalQueue(audit_log=audit),
        report_path=report_path or Path("does-not-exist.json"),
    )
    if seed:
        seed_demo(state)
    app = create_app(settings)
    app.dependency_overrides[get_state] = lambda: state
    return TestClient(app), state


def _greylist_action(summary: str = "Apply labels to #1") -> Action:
    return Action(kind=ActionKind.APPLY_LABELS, repo=TARGET, summary=summary)


def test_health_reports_safety_posture() -> None:
    client, _ = _build()
    body = client.get("/api/health").json()
    assert body == {
        "status": "ok",
        "env": "test",
        "dry_run": True,
        "target_repo": TARGET,
    }


def test_actions_feed_is_most_recent_first_and_capped() -> None:
    client, state = _build()
    for i in range(3):
        action = _greylist_action(f"summary {i}")
        state.approval_queue.request(action, _classify(state, action), trace_id=f"trace-{i}")

    rows = client.get("/api/actions", params={"limit": 2}).json()
    assert len(rows) == 2
    # Most-recent-first: the last requested action appears first.
    assert rows[0]["summary"] == "summary 2"
    assert rows[0]["kind"] == "apply_labels"
    assert rows[0]["verdict"] == "require_approval"
    assert rows[0]["trace_id"] == "trace-2"


def test_approvals_lists_pending_requests() -> None:
    client, state = _build()
    action = _greylist_action("Apply labels to #7")
    pending = state.approval_queue.request(action, _classify(state, action), trace_id="t1")

    rows = client.get("/api/approvals").json()
    assert len(rows) == 1
    assert rows[0]["approval_id"] == pending.approval_id
    assert rows[0]["status"] == "pending"
    assert rows[0]["kind"] == "apply_labels"


def test_approve_transitions_and_audits_human_actor() -> None:
    client, state = _build()
    action = _greylist_action()
    pending = state.approval_queue.request(action, _classify(state, action), trace_id="t1")

    resp = client.post(f"/api/approvals/{pending.approval_id}/approve", json={"by": "maintainer"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["resolved_by"] == "maintainer"
    # The queue, not the route, performed the transition: it is gone from pending.
    assert client.get("/api/approvals").json() == []
    # And the grant is audited as a human actor.
    notes = [r for r in state.audit_log.records() if r.actor == "human:maintainer"]
    assert any("granted" in (r.note or "") for r in notes)


def test_reject_is_terminal() -> None:
    client, state = _build()
    action = _greylist_action()
    pending = state.approval_queue.request(action, _classify(state, action), trace_id="t1")

    resp = client.post(
        f"/api/approvals/{pending.approval_id}/reject",
        json={"by": "maintainer", "note": "not now"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["resolution_note"] == "not now"


def test_approve_unknown_id_is_404() -> None:
    client, _ = _build()
    resp = client.post("/api/approvals/does-not-exist/approve", json={"by": "x"})
    assert resp.status_code == 404


def test_approve_already_resolved_is_409() -> None:
    client, state = _build()
    action = _greylist_action()
    pending = state.approval_queue.request(action, _classify(state, action), trace_id="t1")
    state.approval_queue.approve(pending.approval_id, by="maintainer")

    resp = client.post(f"/api/approvals/{pending.approval_id}/approve", json={"by": "someone"})
    assert resp.status_code == 409


def test_approve_requires_a_by_field() -> None:
    client, state = _build()
    action = _greylist_action()
    pending = state.approval_queue.request(action, _classify(state, action), trace_id="t1")
    resp = client.post(f"/api/approvals/{pending.approval_id}/approve", json={})
    assert resp.status_code == 422


def test_scorecard_absent_when_no_report() -> None:
    client, _ = _build()
    body = client.get("/api/scorecard").json()
    assert body["available"] is False
    assert body["metrics"] == []


def test_scorecard_reads_report(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "generated_at": datetime(2026, 6, 14, tzinfo=UTC).isoformat(),
                "subset": "swe-bench-lite-25",
                "metrics": {"triage_f1": 0.82, "fix_resolved_pct": 24.0},
            }
        ),
        encoding="utf-8",
    )
    client, _ = _build(report_path=report)
    body = client.get("/api/scorecard").json()
    assert body["available"] is True
    assert body["subset"] == "swe-bench-lite-25"
    by_key = {m["key"]: m for m in body["metrics"]}
    assert by_key["triage_f1"]["value"] == 0.82
    assert by_key["fix_resolved_pct"]["unit"] == "%"
    # A metric absent from the report is surfaced as null, not fabricated.
    assert by_key["repro_accuracy"]["value"] is None


def test_load_scorecard_tolerates_malformed_report(tmp_path: Path) -> None:
    report = tmp_path / "bad.json"
    report.write_text("{not json", encoding="utf-8")
    assert load_scorecard(report).available is False


def test_seed_demo_populates_feed_and_queue() -> None:
    client, _ = _build(seed=True)
    actions = client.get("/api/actions").json()
    approvals = client.get("/api/approvals").json()

    # Seed produces read-only allows, queued greylist work, an approval, a deny.
    assert len(actions) >= 6
    assert len(approvals) == 3
    verdicts = {a["verdict"] for a in actions}
    assert {"allow", "require_approval", "deny"} <= verdicts
    # The refused merge is present and clearly a denial.
    assert any(a["kind"] == "merge_pr" and a["verdict"] == "deny" for a in actions)


def _classify(state: ApiState, action: Action) -> PolicyDecision:
    return classify(action, target_repo=state.settings.github_repo or TARGET)


@pytest.fixture(autouse=True)
def _clear_state_cache() -> None:
    get_state.cache_clear()
