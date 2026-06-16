"""The Steward eval suite — first-class product code (CLAUDE.md §10).

Measures the triage capabilities (classification accuracy/F1 and duplicate
precision/recall) against versioned, labeled datasets, writes a report, and
**gates** against a committed baseline so no PR can quietly drop a core metric.
Run it with ``just eval`` / ``python -m steward.evals``.
"""

from __future__ import annotations

from steward.evals.report import EvalReport, Regression, check_regressions
from steward.evals.run import build_report, main

__all__ = ["EvalReport", "Regression", "build_report", "check_regressions", "main"]
