"""The Steward agent graph: triage → reproduce → fix, with backtracking.

The stateful LangGraph graph (CLAUDE.md §3) orchestrates the full cycle behind a
typed :class:`GraphState`, delegating real work to the capability seams in
:mod:`steward.graph.capabilities` and gating any "fixed" claim behind the VERIFY
node. Build it with :func:`build_graph` and drive it with :func:`run_issue`.
"""

from __future__ import annotations

from steward.graph.build import build_graph, run_issue
from steward.graph.capabilities import (
    Classifier,
    Hypothesizer,
    Patcher,
    PullRequestOpener,
    Reproducer,
    StewardDeps,
    Tester,
)
from steward.graph.state import (
    GraphOutcome,
    GraphState,
    OpenedPR,
    ProposedPatch,
    ReproOutcome,
    ReproVerdict,
    RouteTarget,
)

__all__ = [
    "Classifier",
    "GraphOutcome",
    "GraphState",
    "Hypothesizer",
    "OpenedPR",
    "Patcher",
    "ProposedPatch",
    "PullRequestOpener",
    "ReproOutcome",
    "ReproVerdict",
    "Reproducer",
    "RouteTarget",
    "StewardDeps",
    "Tester",
    "build_graph",
    "run_issue",
]
