"""The FastAPI application: a thin read + approval surface (CLAUDE.md §3/§13).

Handlers carry no business logic — they project the audit log / approval queue
into the response views in :mod:`steward.api.schemas` and delegate every
state change to :class:`~steward.policy.approvals.ApprovalQueue`. The queue,
not the route, performs approve/reject, so the policy invariants (greylist
needs approval, rejected/expired are terminal, every transition audited) hold
exactly as they do everywhere else.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from steward.api.schemas import (
    ActionView,
    ApprovalDecisionRequest,
    ApprovalView,
    HealthView,
    ScorecardView,
)
from steward.api.seed import seed_demo
from steward.api.state import ApiState, get_state
from steward.config import Settings, get_settings
from steward.policy.approvals import ApprovalError

# Dashboard dev origins allowed to call the API. Scoped on purpose (CLAUDE.md
# §12): the browser app talks to the API cross-origin, nothing else needs to.
_DASHBOARD_DEV_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)

StateDep = Annotated[ApiState, Depends(get_state)]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app.

    A factory (not a module-level singleton only) so tests can construct an app
    with a specific :class:`Settings` and override :func:`get_state`.
    """
    settings = settings or get_settings()
    app = FastAPI(
        title="Steward API",
        version="0.1.0",
        summary="Read + approval surface over Steward's policy core.",
        description=(
            "Surfaces the append-only audit log, the greylist approval queue, "
            "and the published eval scorecard for the dashboard. Adds no new "
            "world-mutating capability: approve/reject funnel through the "
            "policy approval queue."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_DASHBOARD_DEV_ORIGINS),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    if settings.seed_demo:
        seed_demo(get_state())

    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/api/health", response_model=HealthView, tags=["meta"])
    def health(state: StateDep) -> HealthView:
        """Liveness plus the safety-relevant runtime posture (dry-run, repo)."""
        return HealthView(
            env=state.settings.env,
            dry_run=state.settings.dry_run,
            target_repo=state.settings.github_repo,
        )

    @app.get("/api/actions", response_model=list[ActionView], tags=["audit"])
    def actions(state: StateDep, limit: int = 100) -> list[ActionView]:
        """The audit log, most-recent-first, capped at ``limit`` entries.

        Read-only projection of the append-only audit log — every proposed,
        executed, dry-run, and refused action Steward has recorded.
        """
        capped = max(1, min(limit, 500))
        records = list(state.audit_log.records())
        recent = records[-capped:]
        return [ActionView.from_record(r) for r in reversed(recent)]

    @app.get("/api/approvals", response_model=list[ApprovalView], tags=["approvals"])
    def approvals(state: StateDep) -> list[ApprovalView]:
        """Pending greylist approval requests, oldest first."""
        return [ApprovalView.from_pending(item) for item in state.approval_queue.pending()]

    @app.post(
        "/api/approvals/{approval_id}/approve",
        response_model=ApprovalView,
        tags=["approvals"],
    )
    def approve(approval_id: str, body: ApprovalDecisionRequest, state: StateDep) -> ApprovalView:
        """Approve a pending greylist request via the approval queue.

        The queue performs the transition, mints the :class:`ApprovedAction`
        execution proof, and audits it as ``human:<by>``. Unknown/already
        resolved/expired ids surface as 4xx, never a silent no-op.
        """
        try:
            approved = state.approval_queue.approve(approval_id, by=body.by)
        except ApprovalError as exc:
            raise _approval_http_error(exc) from exc
        return ApprovalView.from_pending(approved.approval)

    @app.post(
        "/api/approvals/{approval_id}/reject",
        response_model=ApprovalView,
        tags=["approvals"],
    )
    def reject(approval_id: str, body: ApprovalDecisionRequest, state: StateDep) -> ApprovalView:
        """Reject a pending greylist request (terminal — it never executes)."""
        try:
            rejected = state.approval_queue.reject(approval_id, by=body.by, note=body.note)
        except ApprovalError as exc:
            raise _approval_http_error(exc) from exc
        return ApprovalView.from_pending(rejected)

    @app.get("/api/scorecard", response_model=ScorecardView, tags=["evals"])
    def scorecard(state: StateDep) -> ScorecardView:
        """The published eval scorecard, or an honest 'not yet measured' state."""
        return state.scorecard()


def _approval_http_error(exc: ApprovalError) -> HTTPException:
    """Map an :class:`ApprovalError` onto the right HTTP status.

    Unknown ids are 404; an invalid transition (already resolved/expired) is a
    409 conflict — the request is well-formed but the resource state forbids it.
    """
    message = str(exc)
    if message.startswith("unknown approval id"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


# The ASGI app uvicorn serves: `uv run uvicorn steward.api.app:app`.
app = create_app()
