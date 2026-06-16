"""The eval report and the baseline regression gate (CLAUDE.md §10).

A run produces an :class:`EvalReport` — a flat ``metrics`` map (what the
scorecard and the gate consume) plus richer ``details`` — written to
``evals/report.json``. The **gate** compares those metrics to
``evals/baseline.json`` and fails when any core metric drops below its baseline
(beyond a small tolerance). Raising the baseline is its own reviewed PR; eval
cases are never weakened to pass.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Metrics are higher-is-better; a drop beyond this tolerance is a regression.
DEFAULT_TOLERANCE = 1e-6

BASELINE_PATH = Path("evals/baseline.json")
REPORT_PATH = Path("evals/report.json")


class EvalReport(BaseModel):
    """One eval run: provenance, the flat metric map, and nested details."""

    generated_at: str
    backend: str
    subset: str
    metrics: dict[str, float] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls, *, backend: str, subset: str, metrics: dict[str, float], details: dict[str, Any]
    ) -> EvalReport:
        return cls(
            generated_at=datetime.now(UTC).isoformat(),
            backend=backend,
            subset=subset,
            metrics={k: round(v, 6) for k, v in metrics.items()},
            details=details,
        )

    def write(self, path: Path = REPORT_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(), indent=2) + "\n", encoding="utf-8")


class Regression(BaseModel):
    """One metric that fell below its baseline."""

    metric: str
    baseline: float
    actual: float

    def describe(self) -> str:
        return f"{self.metric}: {self.actual:.4f} < baseline {self.baseline:.4f}"


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, float]:
    """Load the committed baseline metric map (empty if absent)."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: float(v) for k, v in data.get("metrics", {}).items()}


def check_regressions(
    metrics: dict[str, float],
    baseline: dict[str, float],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[Regression]:
    """Return every baseline metric the run dropped below (beyond ``tolerance``).

    A metric present in the baseline but missing from the run counts as a
    regression (a capability silently stopped being measured).
    """
    regressions: list[Regression] = []
    for metric, base_value in baseline.items():
        actual = metrics.get(metric)
        if actual is None or actual < base_value - tolerance:
            regressions.append(Regression(metric=metric, baseline=base_value, actual=actual or 0.0))
    return regressions
