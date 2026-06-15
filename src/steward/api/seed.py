"""Dev-only seeding of realistic actions so the dashboard demo is non-empty.

Until the live agent (M4) drives the policy core, the in-memory audit log and
approval queue start empty. :func:`seed_demo` populates them with a small,
honest slice of what Steward actually produces — read-only work that was
allowed, greylist mutations queued for approval (one already approved), and a
blacklisted action that was refused — using the **real** policy engine and
approval queue, never fabricated records. It runs only when
``STEWARD_SEED_DEMO`` is set (CLAUDE.md §5: nothing live, dry-run by default).
"""

from __future__ import annotations

from steward.api.state import ApiState
from steward.observability import new_trace_id
from steward.policy.engine import Action, ActionKind, PolicyEngine, PolicyVerdict

# A clearly Steward-owned demo target when no real repo is configured, so the
# seed never implies action on a repository we don't control.
_DEMO_REPO = "stewardbot/demo-shop"


def seed_demo(state: ApiState) -> None:
    """Populate ``state`` with a representative set of actions. Idempotent-ish.

    Safe to call once at startup. Uses the configured target repo when present,
    otherwise a clearly-owned demo repo. All records flow through the genuine
    policy engine and approval queue — this seeds *real* decisions, not mock
    rows.
    """
    repo = state.settings.github_repo or _DEMO_REPO
    engine = PolicyEngine(target_repo=repo)
    queue = state.approval_queue
    audit = state.audit_log

    # 1) Allowed read-only triage work — classified, authorized, audited.
    for kind, summary in (
        (ActionKind.READ_ISSUE, "Read issue #128: 'Checkout total ignores discount code'"),
        (
            ActionKind.FIND_DUPLICATES,
            "Searched for duplicates of #128 (top score 0.71, below 0.85)",
        ),
        (ActionKind.SEARCH_CODE, "Searched codebase for 'apply_discount' (3 hits)"),
    ):
        action = Action(kind=kind, repo=repo, summary=summary)
        decision = engine.classify(action)
        audit.append(
            action=action,
            decision=decision,
            trace_id=new_trace_id(),
            note="allowed: read-only/sandboxed",
        )

    # 2) Greylist mutations queued for human approval (the approval queue).
    comment = Action(
        kind=ActionKind.POST_ISSUE_COMMENT,
        repo=repo,
        summary="Propose triage comment on #128 (bug, confidence 0.88) + needs-info request",
    )
    labels = Action(
        kind=ActionKind.APPLY_LABELS,
        repo=repo,
        summary="Apply labels to #128: type:bug, area:checkout, ai-generated",
    )
    draft_pr = Action(
        kind=ActionKind.OPEN_DRAFT_PR,
        repo=repo,
        summary="Open draft PR for #128 with proof test (fails before, passes after)",
    )
    for action in (comment, labels, draft_pr):
        queue.request(action, engine.classify(action), trace_id=new_trace_id())

    # 3) One greylist action already approved by a human (full lifecycle).
    approved = Action(
        kind=ActionKind.APPLY_LABELS,
        repo=repo,
        summary="Apply labels to #131: type:question, status:needs-info, ai-generated",
    )
    pending = queue.request(approved, engine.classify(approved), trace_id=new_trace_id())
    queue.approve(pending.approval_id, by="maintainer")

    # 4) A blacklisted action that was refused — proof the deny path is audited.
    merge = Action(
        kind=ActionKind.MERGE_PR,
        repo=repo,
        summary="(Refused) merge PR #140 — Steward never merges",
    )
    deny_decision = engine.classify(merge)
    if deny_decision.verdict is PolicyVerdict.DENY:
        audit.append(
            action=merge,
            decision=deny_decision,
            trace_id=new_trace_id(),
            note="refused: blacklisted action can never execute",
        )
