"""Human approval for greylist actions: nothing reversible-but-mutating runs alone.

A greylist verdict (:attr:`PolicyVerdict.REQUIRE_APPROVAL`) means a human must
explicitly approve the action before it can execute, mirroring the product's
human-in-the-loop ethos (CLAUDE.md §1/§6). The :class:`ApprovalQueue` is that
mechanism:

* :meth:`ApprovalQueue.request` accepts **only** a ``require_approval``
  decision — whitelist actions don't need approval and blacklist actions can
  never even be queued — and records the pending action in the audit log.
* :meth:`ApprovalQueue.approve` resolves a pending, unexpired request and is
  the **only producer** of :class:`ApprovedAction`, the greylist counterpart
  of :class:`steward.policy.engine.AuthorizedAction`. Executors demand one of
  those two proof types, so an unapproved greylist action has no code path to
  execution.
* :meth:`ApprovalQueue.reject` and expiry are terminal: a rejected or expired
  request can never be approved afterwards, and every transition is
  audit-logged with the human actor (``human:<login>``) and the ``trace_id``.

Storage is in-memory for now; the dashboard milestone (#26) surfaces this
queue and a durable backend can slot in behind the same surface.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from steward.policy.audit import AuditLog
from steward.policy.engine import Action, PolicyDecision, PolicyVerdict

# How long a pending approval stays actionable unless a caller overrides it.
DEFAULT_APPROVAL_TTL = timedelta(hours=24)


class ApprovalStatus(StrEnum):
    """Lifecycle of one approval request. ``PENDING`` is the only open state."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalError(RuntimeError):
    """Raised on invalid approval transitions or unknown approval ids."""


class PendingApproval(BaseModel):
    """One approval request and its (immutable) state snapshot."""

    model_config = ConfigDict(frozen=True)

    approval_id: str = Field(min_length=1)
    action: Action
    decision: PolicyDecision
    trace_id: str = Field(min_length=1)
    requested_at: datetime
    expires_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class ApprovedAction(BaseModel):
    """Proof that a human approved one greylist action.

    Only :meth:`ApprovalQueue.approve` produces this type — that is what makes
    "greylist always requires approval" structural rather than conventional.
    """

    model_config = ConfigDict(frozen=True)

    action: Action
    decision: PolicyDecision
    approval: PendingApproval


class ApprovalQueue:
    """The pending-approval queue for greylist actions.

    ``audit_log`` receives a record for every transition (requested, approved,
    rejected, expired) carrying the actor and ``trace_id`` (CLAUDE.md §11).
    ``clock`` is injectable for deterministic tests.
    """

    def __init__(
        self,
        *,
        audit_log: AuditLog,
        ttl: timedelta = DEFAULT_APPROVAL_TTL,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        self._audit = audit_log
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(UTC))
        self._items: dict[str, PendingApproval] = {}

    def request(
        self, action: Action, decision: PolicyDecision, *, trace_id: str
    ) -> PendingApproval:
        """Queue ``action`` for human approval and audit the request.

        Raises :class:`ApprovalError` unless ``decision`` is a
        ``require_approval`` verdict for this exact action: an allow verdict
        needs no approval, and a deny verdict must never reach a queue.
        """
        if decision.verdict is not PolicyVerdict.REQUIRE_APPROVAL:
            raise ApprovalError(
                f"only require_approval decisions can be queued, got {decision.verdict.value}"
            )
        if decision.action != action:
            raise ApprovalError("decision does not belong to the submitted action")
        now = self._clock()
        item = PendingApproval(
            approval_id=uuid4().hex,
            action=action,
            decision=decision,
            trace_id=trace_id,
            requested_at=now,
            expires_at=now + self._ttl,
        )
        self._items[item.approval_id] = item
        self._audit.append(
            action=action,
            decision=decision,
            trace_id=trace_id,
            note=f"approval requested ({item.approval_id})",
        )
        return item

    def approve(self, approval_id: str, *, by: str) -> ApprovedAction:
        """Resolve a pending request as approved and return execution proof.

        Raises :class:`ApprovalError` for unknown ids, already-resolved
        requests, and expired requests (which are marked expired and audited —
        they never execute).
        """
        item = self._resolvable(approval_id, by=by)
        resolved = item.model_copy(
            update={
                "status": ApprovalStatus.APPROVED,
                "resolved_by": by,
                "resolved_at": self._clock(),
            }
        )
        self._items[approval_id] = resolved
        self._audit.append(
            action=item.action,
            decision=item.decision,
            trace_id=item.trace_id,
            actor=f"human:{by}",
            note=f"approval granted ({approval_id})",
        )
        return ApprovedAction(action=item.action, decision=item.decision, approval=resolved)

    def reject(self, approval_id: str, *, by: str, note: str | None = None) -> PendingApproval:
        """Resolve a pending request as rejected. Terminal: it never executes."""
        item = self._resolvable(approval_id, by=by)
        resolved = item.model_copy(
            update={
                "status": ApprovalStatus.REJECTED,
                "resolved_by": by,
                "resolved_at": self._clock(),
                "resolution_note": note,
            }
        )
        self._items[approval_id] = resolved
        self._audit.append(
            action=item.action,
            decision=item.decision,
            trace_id=item.trace_id,
            actor=f"human:{by}",
            note=f"approval rejected ({approval_id})",
        )
        return resolved

    def get(self, approval_id: str) -> PendingApproval:
        """Return the current snapshot of one request (expiring it if due)."""
        try:
            item = self._items[approval_id]
        except KeyError as exc:
            raise ApprovalError(f"unknown approval id: {approval_id}") from exc
        return self._expire_if_due(item)

    def pending(self) -> list[PendingApproval]:
        """All still-actionable requests, oldest first (expired ones excluded)."""
        snapshots = [self._expire_if_due(item) for item in self._items.values()]
        actionable = [s for s in snapshots if s.status is ApprovalStatus.PENDING]
        return sorted(actionable, key=lambda s: s.requested_at)

    def _resolvable(self, approval_id: str, *, by: str) -> PendingApproval:
        item = self.get(approval_id)
        if item.status is not ApprovalStatus.PENDING:
            raise ApprovalError(
                f"approval {approval_id} is {item.status.value} and cannot be resolved by {by}"
            )
        return item

    def _expire_if_due(self, item: PendingApproval) -> PendingApproval:
        if item.status is ApprovalStatus.PENDING and self._clock() >= item.expires_at:
            expired = item.model_copy(
                update={"status": ApprovalStatus.EXPIRED, "resolved_at": self._clock()}
            )
            self._items[item.approval_id] = expired
            self._audit.append(
                action=item.action,
                decision=item.decision,
                trace_id=item.trace_id,
                note=f"approval expired ({item.approval_id})",
            )
            return expired
        return item
