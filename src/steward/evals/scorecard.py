"""Render the eval report as the README scorecard table (CLAUDE.md §1/§10).

The scorecard is published honestly — including where Steward isn't measured
yet. This turns an :class:`~steward.evals.report.EvalReport` into the markdown
table that lives in the README, so updating it is mechanical: regenerate the
report with ``just eval`` and paste the output of
``python -m steward.evals.scorecard``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from steward.config import get_settings
from steward.evals.report import REPORT_PATH, EvalReport
from steward.evals.run import build_report

# Rows sourced from the report's flat metric map, in display order.
_METRIC_ROWS: tuple[tuple[str, str, str], ...] = (
    ("triage_f1", "Triage classification (macro-F1)", "score"),
    ("triage_accuracy", "Triage classification (accuracy)", "score"),
    ("injection_recall", "Prompt-injection surfacing (recall)", "score"),
    ("dedup_precision", "Duplicate detection (precision)", "score"),
    ("dedup_recall", "Duplicate detection (recall)", "score"),
    ("repro_accuracy", "Reproduction verdict (accuracy)", "score"),
    ("review_accuracy", "Review council verdict (accuracy)", "score"),
    ("review_f1", "Review council verdict (macro-F1)", "score"),
)

# Capabilities not yet measured — shown honestly rather than omitted.
_PENDING_ROWS: tuple[tuple[str, str], ...] = (
    ("Fix success — SWE-bench Lite (% resolved)", "not yet measured (#22)"),
    ("Avg cost / action (USD)", "not yet measured (live run)"),
    ("Avg latency / action (s)", "not yet measured (live run)"),
)


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def render_scorecard(report: EvalReport) -> str:
    """Render ``report`` as the README scorecard markdown."""
    lines = [
        "| Capability | Result |",
        "| ---------- | ------ |",
    ]
    for key, label, _unit in _METRIC_ROWS:
        lines.append(f"| {label} | {_fmt(report.metrics.get(key))} |")
    for label, note in _PENDING_ROWS:
        lines.append(f"| {label} | {note} |")
    table = "\n".join(lines)
    provenance = (
        f"_Subset `{report.subset}` · backend **{report.backend}** · "
        f"generated {report.generated_at[:10]}._"
    )
    return f"{table}\n\n{provenance}\n"


def load_or_build_report() -> EvalReport:
    """Load the last ``evals/report.json`` if present, else run the suite."""
    if REPORT_PATH.exists():
        data = json.loads(Path(REPORT_PATH).read_text(encoding="utf-8"))
        return EvalReport.model_validate(data)
    return build_report(get_settings())


def main() -> int:
    print(render_scorecard(load_or_build_report()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
