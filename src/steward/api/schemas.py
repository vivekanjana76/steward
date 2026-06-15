"""Pydantic request/response models for the API (CLAUDE.md §13).

Every endpoint body is a typed model so the OpenAPI schema is precise and the
dashboard has a stable contract. The audit log, policy decision, and approval
models live in :mod:`steward.policy`; here we define the flattened *views* the
UI consumes plus the small request bodies for approve/reject.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from steward.policy.approvals import ApprovalStatus, PendingApproval
from steward.policy.audit import AuditRecord
from steward.policy.engine import PolicyVerdict


class HealthView(BaseModel):
    """Liveness and the safety-relevant runtime posture of the service."""

    status: str = "ok"
    env: str
    dry_run: bool
    target_repo: str | None


class ActionView(BaseModel):
    """A flattened audit record for the actions feed.

    Flattens :class:`~steward.policy.audit.AuditRecord` into the fields the UI
    renders, and surfaces ``entry_hash`` so the dashboard can show the
    tamper-evident chain anchor without exposing the full hash plumbing.
    """

    seq: int
    timestamp: datetime
    trace_id: str
    actor: str
    kind: str
    repo: str
    summary: str
    verdict: PolicyVerdict
    rule: str
    reason: str
    dry_run: bool
    executed: bool
    note: str | None
    entry_hash: str

    @classmethod
    def from_record(cls, record: AuditRecord) -> ActionView:
        """Project an :class:`AuditRecord` onto the UI-facing view."""
        return cls(
            seq=record.seq,
            timestamp=record.timestamp,
            trace_id=record.trace_id,
            actor=record.actor,
            kind=record.action.kind.value,
            repo=record.action.repo,
            summary=record.action.summary,
            verdict=record.decision.verdict,
            rule=record.decision.rule,
            reason=record.decision.reason,
            dry_run=record.dry_run,
            executed=record.executed,
            note=record.note,
            entry_hash=record.entry_hash,
        )


class ApprovalView(BaseModel):
    """A pending (or resolved) approval request, projected for the UI."""

    approval_id: str
    kind: str
    repo: str
    summary: str
    reason: str
    trace_id: str
    requested_at: datetime
    expires_at: datetime
    status: ApprovalStatus
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_note: str | None

    @classmethod
    def from_pending(cls, item: PendingApproval) -> ApprovalView:
        """Project a :class:`PendingApproval` onto the UI-facing view."""
        return cls(
            approval_id=item.approval_id,
            kind=item.action.kind.value,
            repo=item.action.repo,
            summary=item.action.summary,
            reason=item.decision.reason,
            trace_id=item.trace_id,
            requested_at=item.requested_at,
            expires_at=item.expires_at,
            status=item.status,
            resolved_by=item.resolved_by,
            resolved_at=item.resolved_at,
            resolution_note=item.resolution_note,
        )


class ApprovalDecisionRequest(BaseModel):
    """Body for approve/reject: who acted, and an optional note.

    ``by`` is the human login recorded in the audit log as ``human:<by>``
    (CLAUDE.md §11) — the approval queue, not the route, performs the
    transition.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    by: str = Field(min_length=1, max_length=100, description="Human login resolving the request")
    note: str | None = Field(default=None, max_length=2000)


class ScorecardMetric(BaseModel):
    """One published metric: a value, its unit, and where it came from."""

    key: str
    label: str
    value: float | None
    unit: str
    note: str | None = None


class ScorecardView(BaseModel):
    """The published scorecard (CLAUDE.md §1/§10).

    ``available`` is ``False`` until the eval harness (M6, #20-#24) writes a
    report; the dashboard renders an honest "not yet measured" state rather
    than fabricating numbers.
    """

    available: bool
    generated_at: datetime | None = None
    subset: str | None = None
    source: str | None = None
    metrics: list[ScorecardMetric] = Field(default_factory=list)
