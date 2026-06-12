"""The safety suite — release blockers, every one (CLAUDE.md §5/§9).

These tests prove the structural guarantees of bounded autonomy end to end:
blacklist actions cannot execute through any path (even wrapped in forged
proof objects), greylist actions always require a granted approval, dry-run
is the default and performs no external mutation, and live execution demands
both the global flag and a per-kind opt-in. A failure here is a release
blocker — never weaken or delete one of these to make a change pass.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from steward.config import Settings
from steward.policy import (
    Action,
    ActionKind,
    ApprovalError,
    ApprovalQueue,
    ApprovedAction,
    AuthorizedAction,
    InMemoryAuditLog,
    PolicyEngine,
    PolicyList,
    PolicyViolationError,
    classify,
    list_for,
)
from steward.policy.execute import ExecutionGate, ExecutionStatus, live_action_kinds

TARGET = "vivekanjana76/steward-demo"
FIXED_NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)

BLACKLIST = [k for k in ActionKind if list_for(k) is PolicyList.BLACKLIST]
GREYLIST = [k for k in ActionKind if list_for(k) is PolicyList.GREYLIST]
WHITELIST = [k for k in ActionKind if list_for(k) is PolicyList.WHITELIST]


def _settings(**env: str) -> Settings:
    base = {"STEWARD_GITHUB_REPO": TARGET}
    base.update(env)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def _action(kind: ActionKind) -> Action:
    return Action(kind=kind, repo=TARGET, summary=f"safety test {kind.value}")


def _gate(settings: Settings, audit: InMemoryAuditLog) -> ExecutionGate:
    return ExecutionGate(settings=settings, audit_log=audit)


def _forged_authorization(kind: ActionKind) -> AuthorizedAction:
    """Build proof an attacker could forge: a hand-rolled AuthorizedAction."""
    action = _action(kind)
    # Use a *whitelist* decision object for a different action to make the
    # forgery as convincing as possible.
    benign = classify(_action(ActionKind.READ_ISSUE), target_repo=TARGET)
    return AuthorizedAction.model_construct(action=action, decision=benign)


@pytest.fixture
def audit() -> InMemoryAuditLog:
    return InMemoryAuditLog(clock=lambda: FIXED_NOW)


class TestBlacklistIsImpossible:
    @pytest.mark.parametrize("kind", BLACKLIST)
    def test_engine_never_authorizes(self, kind: ActionKind) -> None:
        with pytest.raises(PolicyViolationError):
            PolicyEngine(target_repo=TARGET).authorize(_action(kind))

    @pytest.mark.parametrize("kind", BLACKLIST)
    def test_queue_never_accepts(self, kind: ActionKind, audit: InMemoryAuditLog) -> None:
        queue = ApprovalQueue(audit_log=audit, clock=lambda: FIXED_NOW)
        action = _action(kind)
        with pytest.raises(ApprovalError):
            queue.request(action, classify(action, target_repo=TARGET), trace_id="t")

    @pytest.mark.parametrize("kind", BLACKLIST)
    def test_gate_refuses_even_forged_proof(
        self, kind: ActionKind, audit: InMemoryAuditLog
    ) -> None:
        # Even with dry-run off and the kind opted in live, a forged
        # AuthorizedAction wrapping a blacklisted action is re-classified and
        # refused — and the refusal is audited.
        settings = _settings(STEWARD_DRY_RUN="false", STEWARD_LIVE_ACTIONS=kind.value)
        gate = _gate(settings, audit)
        calls: list[Action] = []
        with pytest.raises(PolicyViolationError):
            gate.execute(_forged_authorization(kind), calls.append, trace_id="t")
        assert calls == []  # the executor was never invoked
        last = list(audit.records())[-1]
        assert last.executed is False
        assert "refused" in (last.note or "")


class TestGreylistAlwaysNeedsApproval:
    @pytest.mark.parametrize("kind", GREYLIST)
    def test_engine_never_authorizes_greylist_directly(self, kind: ActionKind) -> None:
        with pytest.raises(PolicyViolationError):
            PolicyEngine(target_repo=TARGET).authorize(_action(kind))

    @pytest.mark.parametrize("kind", GREYLIST)
    def test_gate_refuses_greylist_without_granted_approval(
        self, kind: ActionKind, audit: InMemoryAuditLog
    ) -> None:
        settings = _settings(STEWARD_DRY_RUN="false", STEWARD_LIVE_ACTIONS=kind.value)
        gate = _gate(settings, audit)
        calls: list[Action] = []
        with pytest.raises(PolicyViolationError):
            gate.execute(_forged_authorization(kind), calls.append, trace_id="t")
        assert calls == []

    def test_gate_refuses_rejected_approval(self, audit: InMemoryAuditLog) -> None:
        queue = ApprovalQueue(audit_log=audit, clock=lambda: FIXED_NOW)
        action = _action(ActionKind.POST_ISSUE_COMMENT)
        item = queue.request(action, classify(action, target_repo=TARGET), trace_id="t")
        rejected = queue.reject(item.approval_id, by="vivek")
        forged = ApprovedAction.model_construct(
            action=action,
            decision=classify(action, target_repo=TARGET),
            approval=rejected,
        )
        settings = _settings(STEWARD_DRY_RUN="false", STEWARD_LIVE_ACTIONS=action.kind.value)
        with pytest.raises(PolicyViolationError):
            _gate(settings, audit).execute(forged, lambda a: None, trace_id="t")

    def test_granted_approval_executes_when_live(self, audit: InMemoryAuditLog) -> None:
        queue = ApprovalQueue(audit_log=audit, clock=lambda: FIXED_NOW)
        action = _action(ActionKind.POST_ISSUE_COMMENT)
        item = queue.request(action, classify(action, target_repo=TARGET), trace_id="t")
        approved = queue.approve(item.approval_id, by="vivek")
        settings = _settings(STEWARD_DRY_RUN="false", STEWARD_LIVE_ACTIONS=action.kind.value)
        calls: list[Action] = []
        result = _gate(settings, audit).execute(approved, calls.append, trace_id="t")
        assert result.status is ExecutionStatus.EXECUTED
        assert calls == [action]


class TestDryRunDefault:
    def test_global_default_is_dry_run(self) -> None:
        assert _settings().dry_run is True

    @pytest.mark.parametrize("kind", WHITELIST)
    def test_dry_run_performs_no_mutation_but_audits(
        self, kind: ActionKind, audit: InMemoryAuditLog
    ) -> None:
        gate = _gate(_settings(), audit)
        proof = PolicyEngine(target_repo=TARGET).authorize(_action(kind))
        calls: list[Action] = []
        result = gate.execute(proof, calls.append, trace_id="trace-dry")
        assert result.status is ExecutionStatus.DRY_RUN
        assert calls == []  # no external mutation
        record = list(audit.records())[-1]
        assert record.dry_run is True
        assert record.executed is False
        assert record.trace_id == "trace-dry"

    def test_live_needs_global_flag_off(self, audit: InMemoryAuditLog) -> None:
        # Per-kind opt-in alone is not enough while dry_run is on.
        settings = _settings(STEWARD_LIVE_ACTIONS=ActionKind.READ_ISSUE.value)
        proof = PolicyEngine(target_repo=TARGET).authorize(_action(ActionKind.READ_ISSUE))
        result = _gate(settings, audit).execute(proof, lambda a: "ran", trace_id="t")
        assert result.status is ExecutionStatus.DRY_RUN

    def test_live_needs_per_kind_opt_in(self, audit: InMemoryAuditLog) -> None:
        # The global flag alone is not enough without the per-kind opt-in.
        settings = _settings(STEWARD_DRY_RUN="false")
        proof = PolicyEngine(target_repo=TARGET).authorize(_action(ActionKind.READ_ISSUE))
        result = _gate(settings, audit).execute(proof, lambda a: "ran", trace_id="t")
        assert result.status is ExecutionStatus.DRY_RUN

    def test_live_executes_with_both_opt_ins(self, audit: InMemoryAuditLog) -> None:
        settings = _settings(
            STEWARD_DRY_RUN="false", STEWARD_LIVE_ACTIONS=ActionKind.READ_ISSUE.value
        )
        proof = PolicyEngine(target_repo=TARGET).authorize(_action(ActionKind.READ_ISSUE))
        result = _gate(settings, audit).execute(proof, lambda a: "ran", trace_id="t")
        assert result.status is ExecutionStatus.EXECUTED
        assert result.output == "ran"
        record = list(audit.records())[-1]
        assert record.executed is True
        assert record.dry_run is False


class TestLiveOptInParsing:
    def test_empty_means_nothing_live(self) -> None:
        assert live_action_kinds(_settings()) == frozenset()

    def test_parses_known_kinds(self) -> None:
        settings = _settings(STEWARD_LIVE_ACTIONS=" read_issue , apply_labels ")
        assert live_action_kinds(settings) == {
            ActionKind.READ_ISSUE,
            ActionKind.APPLY_LABELS,
        }

    def test_unknown_kind_is_an_error_not_a_silent_noop(self) -> None:
        with pytest.raises(PolicyViolationError):
            live_action_kinds(_settings(STEWARD_LIVE_ACTIONS="merge_everything"))

    def test_gate_requires_target_repo(self, audit: InMemoryAuditLog) -> None:
        with pytest.raises(PolicyViolationError):
            ExecutionGate(
                settings=Settings(_env_file=None),  # type: ignore[call-arg]
                audit_log=audit,
            )
