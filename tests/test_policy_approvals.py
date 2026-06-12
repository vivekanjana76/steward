"""Unit tests for the approval queue — safety-critical (CLAUDE.md §9).

Cover the approve, reject, and timeout paths; prove that rejected/expired
requests never execute; and assert every transition is audit-logged with the
actor and trace_id. Deterministic via an injectable, advanceable clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from steward.policy import (
    Action,
    ActionKind,
    InMemoryAuditLog,
    classify,
    verify_chain,
)
from steward.policy.approvals import (
    ApprovalError,
    ApprovalQueue,
    ApprovalStatus,
    ApprovedAction,
)

TARGET = "vivekanjana76/steward-demo"
START = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


class AdvanceableClock:
    """A fake clock the tests move forward explicitly."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def clock() -> AdvanceableClock:
    return AdvanceableClock()


@pytest.fixture
def audit(clock: AdvanceableClock) -> InMemoryAuditLog:
    return InMemoryAuditLog(clock=clock)


@pytest.fixture
def queue(audit: InMemoryAuditLog, clock: AdvanceableClock) -> ApprovalQueue:
    return ApprovalQueue(audit_log=audit, ttl=timedelta(hours=1), clock=clock)


def _greylist_action() -> Action:
    return Action(kind=ActionKind.POST_ISSUE_COMMENT, repo=TARGET, summary="triage comment")


def _request(queue: ApprovalQueue, trace_id: str = "trace-1"):
    action = _greylist_action()
    return queue.request(action, classify(action, target_repo=TARGET), trace_id=trace_id)


class TestRequest:
    def test_greylist_decision_becomes_pending(self, queue: ApprovalQueue) -> None:
        item = _request(queue)
        assert item.status is ApprovalStatus.PENDING
        assert queue.pending() == [item]

    def test_allow_decision_cannot_be_queued(self, queue: ApprovalQueue) -> None:
        action = Action(kind=ActionKind.READ_ISSUE, repo=TARGET, summary="read")
        with pytest.raises(ApprovalError):
            queue.request(action, classify(action, target_repo=TARGET), trace_id="t")

    def test_deny_decision_cannot_be_queued(self, queue: ApprovalQueue) -> None:
        action = Action(kind=ActionKind.MERGE_PR, repo=TARGET, summary="merge")
        with pytest.raises(ApprovalError):
            queue.request(action, classify(action, target_repo=TARGET), trace_id="t")

    def test_mismatched_decision_is_rejected(self, queue: ApprovalQueue) -> None:
        action = _greylist_action()
        other = Action(kind=ActionKind.APPLY_LABELS, repo=TARGET, summary="labels")
        with pytest.raises(ApprovalError):
            queue.request(action, classify(other, target_repo=TARGET), trace_id="t")

    def test_request_is_audited_with_trace_id(
        self, queue: ApprovalQueue, audit: InMemoryAuditLog
    ) -> None:
        _request(queue, trace_id="trace-req")
        records = list(audit.records())
        assert len(records) == 1
        assert records[0].trace_id == "trace-req"
        assert "approval requested" in (records[0].note or "")


class TestApprove:
    def test_approve_yields_execution_proof(self, queue: ApprovalQueue) -> None:
        item = _request(queue)
        approved = queue.approve(item.approval_id, by="vivek")
        assert isinstance(approved, ApprovedAction)
        assert approved.approval.status is ApprovalStatus.APPROVED
        assert approved.approval.resolved_by == "vivek"
        assert queue.pending() == []

    def test_approve_is_audited_with_human_actor(
        self, queue: ApprovalQueue, audit: InMemoryAuditLog
    ) -> None:
        item = _request(queue, trace_id="trace-x")
        queue.approve(item.approval_id, by="vivek")
        request_rec, approve_rec = list(audit.records())
        assert approve_rec.actor == "human:vivek"
        assert approve_rec.trace_id == "trace-x"
        assert "approval granted" in (approve_rec.note or "")
        verify_chain([request_rec, approve_rec])

    def test_double_approval_raises(self, queue: ApprovalQueue) -> None:
        item = _request(queue)
        queue.approve(item.approval_id, by="vivek")
        with pytest.raises(ApprovalError):
            queue.approve(item.approval_id, by="vivek")

    def test_unknown_id_raises(self, queue: ApprovalQueue) -> None:
        with pytest.raises(ApprovalError):
            queue.approve("nope", by="vivek")


class TestReject:
    def test_rejected_request_is_terminal(self, queue: ApprovalQueue) -> None:
        item = _request(queue)
        rejected = queue.reject(item.approval_id, by="vivek", note="not now")
        assert rejected.status is ApprovalStatus.REJECTED
        assert rejected.resolution_note == "not now"
        # A rejected action can never be approved afterwards — it never executes.
        with pytest.raises(ApprovalError):
            queue.approve(item.approval_id, by="vivek")

    def test_reject_is_audited_with_human_actor(
        self, queue: ApprovalQueue, audit: InMemoryAuditLog
    ) -> None:
        item = _request(queue)
        queue.reject(item.approval_id, by="vivek")
        records = list(audit.records())
        assert records[-1].actor == "human:vivek"
        assert "approval rejected" in (records[-1].note or "")


class TestTimeout:
    def test_expired_request_cannot_be_approved(
        self, queue: ApprovalQueue, clock: AdvanceableClock
    ) -> None:
        item = _request(queue)
        clock.advance(timedelta(hours=2))
        with pytest.raises(ApprovalError):
            queue.approve(item.approval_id, by="vivek")
        assert queue.get(item.approval_id).status is ApprovalStatus.EXPIRED

    def test_expiry_is_audited(
        self, queue: ApprovalQueue, audit: InMemoryAuditLog, clock: AdvanceableClock
    ) -> None:
        item = _request(queue)
        clock.advance(timedelta(hours=2))
        assert queue.pending() == []
        records = list(audit.records())
        assert "approval expired" in (records[-1].note or "")
        assert records[-1].trace_id == item.trace_id

    def test_resolution_before_expiry_wins(
        self, queue: ApprovalQueue, clock: AdvanceableClock
    ) -> None:
        item = _request(queue)
        clock.advance(timedelta(minutes=59))
        approved = queue.approve(item.approval_id, by="vivek")
        clock.advance(timedelta(hours=2))
        # Already-approved requests do not flip to expired later.
        assert queue.get(item.approval_id).status is ApprovalStatus.APPROVED
        assert approved.approval.status is ApprovalStatus.APPROVED


class TestQueueBehavior:
    def test_pending_is_oldest_first(self, queue: ApprovalQueue, clock: AdvanceableClock) -> None:
        first = _request(queue, trace_id="t1")
        clock.advance(timedelta(minutes=5))
        second = _request(queue, trace_id="t2")
        assert [i.approval_id for i in queue.pending()] == [
            first.approval_id,
            second.approval_id,
        ]

    def test_non_positive_ttl_rejected(self, audit: InMemoryAuditLog) -> None:
        with pytest.raises(ValueError):
            ApprovalQueue(audit_log=audit, ttl=timedelta(0))
