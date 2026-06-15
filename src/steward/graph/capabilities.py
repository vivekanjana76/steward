"""The capability seams the graph orchestrates.

The graph owns *control flow* — routing, backtracking, and the VERIFY gate — but
delegates the actual work to a small set of protocols. Triage is wired to the
real :class:`~steward.triage.classify.IssueClassifier`; reproduction, patching,
and PR-opening are protocols whose production implementations land in their own
issues (#15 patch+proof, #16 draft PR) and route through the policy engine
there. Defining them as seams lets this issue (#14) build and test the full
orchestration today against deterministic fakes, with nothing stubbed inside the
graph itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from steward.graph.state import GraphState, OpenedPR, ProposedPatch, ReproOutcome
from steward.sandbox import SandboxResult
from steward.triage.classify import TriageDecision
from steward.triage.models import NormalizedIssue


class Classifier(Protocol):
    """Classifies an issue into a grounded triage decision.

    The real :class:`~steward.triage.classify.IssueClassifier` satisfies this
    structurally; tests supply a fake. Kept as a seam so the graph depends on
    the capability, not a concrete class.
    """

    def classify(self, issue: NormalizedIssue) -> TriageDecision: ...


class Reproducer(Protocol):
    """Attempts to reproduce a reported bug in the sandbox.

    Returns a grounded :class:`ReproOutcome`: a ``REPRODUCED`` verdict must carry
    the failing sandbox run as evidence (CLAUDE.md §1).
    """

    def reproduce(self, issue: NormalizedIssue) -> ReproOutcome: ...


class Hypothesizer(Protocol):
    """Proposes a cause hypothesis for a reproduced bug (Opus, via the client)."""

    def hypothesize(self, state: GraphState) -> str: ...


class Patcher(Protocol):
    """Generates a candidate patch plus the proof test for the current hypothesis."""

    def propose(self, state: GraphState) -> ProposedPatch: ...


class Tester(Protocol):
    """Applies the candidate patch in the sandbox and runs its proof test.

    The returned :class:`SandboxResult` is the evidence the VERIFY node checks —
    no "fixed" claim is emitted without it (CLAUDE.md §1/§3).
    """

    def run_proof(self, state: GraphState) -> SandboxResult: ...


class PullRequestOpener(Protocol):
    """Opens a draft PR for a verified fix (routed through policy in #16)."""

    def open_draft(self, state: GraphState) -> OpenedPR: ...


@dataclass(frozen=True, slots=True)
class StewardDeps:
    """The collaborators every node needs, injected once when the graph is built.

    Bundling them keeps node functions pure with respect to their inputs and
    makes the whole graph trivially testable: a test supplies fakes here and
    drives real control flow.
    """

    classifier: Classifier
    reproducer: Reproducer
    hypothesizer: Hypothesizer
    patcher: Patcher
    tester: Tester
    pr_opener: PullRequestOpener
