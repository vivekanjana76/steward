"""Steward's FastAPI service: a read + approval surface over the policy core.

The service is intentionally thin (CLAUDE.md §13). It exposes the **existing**
audit log, approval queue, and eval scorecard so the dashboard (#26) can render
them, and it adds **no new world-mutating capability** of its own — the only
state-changing endpoints are approve/reject, which funnel through
:class:`steward.policy.approvals.ApprovalQueue`, preserving every policy
invariant.
"""

from __future__ import annotations

from steward.api.app import app, create_app

__all__ = ["app", "create_app"]
