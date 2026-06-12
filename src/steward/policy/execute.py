"""The execution gate: the single funnel through which mutations may run.

New action types ship in dry-run, behind the policy engine, with an audit
entry, before they are ever allowed to execute live (CLAUDE.md §5). The
:class:`ExecutionGate` enforces that as the last line of defence:

* **Dry-run is the global default** (``Settings.dry_run`` is ``True``).
  Executing live requires *both* turning the global flag off *and* opting the
  specific :class:`~steward.policy.engine.ActionKind` in via
  ``STEWARD_LIVE_ACTIONS`` — per-kind, explicit, never implicit.
* **Proof is required and re-verified.** Callers hand the gate an
  :class:`~steward.policy.engine.AuthorizedAction` (whitelist) or an
  :class:`~steward.policy.approvals.ApprovedAction` (greylist). The gate does
  not trust the proof object: it **re-classifies the action itself** and
  demands that the proof type match the fresh verdict — so a forged proof
  wrapping a blacklisted or unapproved action still cannot execute.
* **Every outcome is audited** — dry-run, executed, or refused — with the
  ``trace_id``, so the audit log is complete even for actions that never ran.

The dry-run path performs no external mutation: the executor callable is
simply never invoked.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from steward.config import Settings
from steward.policy.approvals import ApprovalStatus, ApprovedAction
from steward.policy.audit import AuditLog, AuditRecord
from steward.policy.engine import (
    Action,
    ActionKind,
    AuthorizedAction,
    PolicyVerdict,
    PolicyViolationError,
    classify,
)

# An executor performs the real-world side effect for one action. The gate is
# the only caller, and only on the live path.
Executor = Callable[[Action], Any]


class ExecutionStatus(StrEnum):
    """How the gate disposed of one proven action."""

    DRY_RUN = "dry_run"
    EXECUTED = "executed"


class ExecutionResult(BaseModel):
    """The auditable outcome of submitting one action to the gate."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    action: Action
    status: ExecutionStatus
    audit_record: AuditRecord
    output: Any | None = None


def live_action_kinds(settings: Settings) -> frozenset[ActionKind]:
    """Parse ``STEWARD_LIVE_ACTIONS`` into the per-kind live opt-in set.

    Raises :class:`PolicyViolationError` on an unknown kind so a typo can
    never silently enable (or fail to enable) live execution.
    """
    raw = (settings.live_actions or "").strip()
    if not raw:
        return frozenset()
    kinds: set[ActionKind] = set()
    for token in raw.split(","):
        name = token.strip()
        if not name:
            continue
        try:
            kinds.add(ActionKind(name))
        except ValueError as exc:
            raise PolicyViolationError(
                f"STEWARD_LIVE_ACTIONS names an unknown action kind: {name!r}"
            ) from exc
    return frozenset(kinds)


class ExecutionGate:
    """Runs proven actions — dry-run by default, live only on explicit opt-in.

    ``target_repo`` scopes re-classification; ``audit_log`` receives a record
    for every submission, including refusals.
    """

    def __init__(self, *, settings: Settings, audit_log: AuditLog) -> None:
        if not settings.github_repo:
            raise PolicyViolationError(
                "STEWARD_GITHUB_REPO is not set; the execution gate requires an "
                "explicit target repository"
            )
        self._target_repo = settings.github_repo
        self._dry_run = settings.dry_run
        self._live_kinds = live_action_kinds(settings)
        self._audit = audit_log

    def execute(
        self,
        proof: AuthorizedAction | ApprovedAction,
        executor: Executor,
        *,
        trace_id: str,
    ) -> ExecutionResult:
        """Dispose of one proven action: dry-run it, execute it, or refuse.

        The proof is not trusted: the action is re-classified and the proof
        type must match the fresh verdict (whitelist → ``AuthorizedAction``,
        greylist → ``ApprovedAction`` whose approval was granted). Anything
        else — including any blacklisted action, whatever it is wrapped in —
        raises :class:`PolicyViolationError` after writing an audit record.
        """
        action = proof.action
        decision = classify(action, target_repo=self._target_repo)
        refusal = self._refusal_reason(proof, decision.verdict)
        if refusal is not None:
            self._audit.append(
                action=action,
                decision=decision,
                trace_id=trace_id,
                dry_run=self._dry_run,
                executed=False,
                note=f"refused: {refusal}",
            )
            raise PolicyViolationError(
                f"refusing to execute {action.kind.value} on {action.repo}: {refusal}"
            )

        if self._dry_run or action.kind not in self._live_kinds:
            record = self._audit.append(
                action=action,
                decision=decision,
                trace_id=trace_id,
                dry_run=True,
                executed=False,
                note="dry-run: no external mutation performed",
            )
            return ExecutionResult(
                action=action, status=ExecutionStatus.DRY_RUN, audit_record=record
            )

        output = executor(action)
        record = self._audit.append(
            action=action,
            decision=decision,
            trace_id=trace_id,
            dry_run=False,
            executed=True,
            note="executed live",
        )
        return ExecutionResult(
            action=action,
            status=ExecutionStatus.EXECUTED,
            audit_record=record,
            output=output,
        )

    @staticmethod
    def _refusal_reason(
        proof: AuthorizedAction | ApprovedAction, verdict: PolicyVerdict
    ) -> str | None:
        """Why ``proof`` does not entitle its action to run, or ``None`` if it does."""
        if verdict is PolicyVerdict.DENY:
            return "the action is denied by policy regardless of any proof object"
        if verdict is PolicyVerdict.ALLOW:
            if not isinstance(proof, AuthorizedAction):
                return "a whitelist action requires an AuthorizedAction from the policy engine"
            return None
        # REQUIRE_APPROVAL
        if not isinstance(proof, ApprovedAction):
            return "a greylist action requires an ApprovedAction from the approval queue"
        if proof.approval.status is not ApprovalStatus.APPROVED:
            return f"the approval is {proof.approval.status.value}, not granted"
        return None
