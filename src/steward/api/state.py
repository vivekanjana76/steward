"""Shared service state and dependency wiring for the API.

The API reads from one :class:`~steward.policy.audit.AuditLog` and drives one
:class:`~steward.policy.approvals.ApprovalQueue`; both are constructed once and
shared across requests. Tests build an :class:`ApiState` directly with stubbed
collaborators and override :func:`get_state`, so no route ever reaches for a
global.

The audit log and approval queue are in-memory for now (the queue already is;
see :mod:`steward.policy.approvals`). A durable backend slots in behind the same
protocols without touching the API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from steward.api.schemas import ScorecardMetric, ScorecardView
from steward.config import Settings, get_settings
from steward.policy.approvals import ApprovalQueue
from steward.policy.audit import AuditLog, InMemoryAuditLog

# Where the eval harness (M6, #20-#24) writes its machine-readable report. Read
# lazily; absent until evals land, in which case the scorecard reports
# "not yet measured" rather than inventing numbers (CLAUDE.md §10).
_DEFAULT_REPORT_PATH = Path("evals/report.json")

# The metrics the scorecard publishes, in display order, with their units. The
# values are filled from the eval report when present.
_SCORECARD_SPEC: tuple[tuple[str, str, str], ...] = (
    ("triage_f1", "Triage F1", "score"),
    ("dedup_precision", "Dedup precision", "score"),
    ("dedup_recall", "Dedup recall", "score"),
    ("repro_accuracy", "Repro verdict accuracy", "score"),
    ("fix_resolved_pct", "Fix % resolved (SWE-bench)", "%"),
    ("avg_cost_usd", "Avg cost / action", "USD"),
    ("avg_latency_s", "Avg latency / action", "s"),
)


@dataclass(slots=True)
class ApiState:
    """The collaborators a request handler needs, bundled for injection."""

    settings: Settings
    audit_log: AuditLog
    approval_queue: ApprovalQueue
    report_path: Path = _DEFAULT_REPORT_PATH

    @classmethod
    def from_settings(cls, settings: Settings) -> ApiState:
        """Build a fresh state with an in-memory audit log + approval queue."""
        audit_log = InMemoryAuditLog()
        queue = ApprovalQueue(audit_log=audit_log)
        return cls(settings=settings, audit_log=audit_log, approval_queue=queue)

    def scorecard(self) -> ScorecardView:
        """Read the eval report into a :class:`ScorecardView`, or report absence."""
        return load_scorecard(self.report_path)


def load_scorecard(path: Path) -> ScorecardView:
    """Build the scorecard from the eval report at ``path``.

    Returns an ``available=False`` view when the report is missing or
    unparseable, so the dashboard renders an honest empty state instead of
    fabricated metrics.
    """
    if not path.exists():
        return ScorecardView(available=False)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ScorecardView(available=False)

    raw_metrics = data.get("metrics", {}) if isinstance(data, dict) else {}
    metrics = [
        ScorecardMetric(
            key=key,
            label=label,
            value=_coerce_float(raw_metrics.get(key)),
            unit=unit,
        )
        for key, label, unit in _SCORECARD_SPEC
    ]
    generated_at = data.get("generated_at") if isinstance(data, dict) else None
    return ScorecardView(
        available=True,
        generated_at=generated_at,
        subset=data.get("subset") if isinstance(data, dict) else None,
        source=str(path),
        metrics=metrics,
    )


def _coerce_float(value: object) -> float | None:
    """Best-effort numeric coercion; ``None`` for missing/non-numeric values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


@lru_cache
def get_state() -> ApiState:
    """Return the process-wide :class:`ApiState` singleton.

    Overridden in tests via ``app.dependency_overrides[get_state]`` so handlers
    run against injected stubs with no shared global.
    """
    return ApiState.from_settings(get_settings())
