"""Typed state for the Steward agent graph (CLAUDE.md §3/§4).

Every node boundary is a Pydantic model: the graph threads one
:class:`GraphState` through triage → route → reproduce → hypothesize → patch →
test → VERIFY → open-draft-PR, and each node returns a partial update validated
back into the state. Grounding is structural — the verdict fields
(:class:`ReproOutcome`, ``test_result``, ``verified``) only ever hold values a
node could justify with evidence, never an unbacked claim (CLAUDE.md §1).
"""

from __future__ import annotations

import operator
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from steward.sandbox import SandboxResult
from steward.triage.classify import TriageDecision
from steward.triage.models import NormalizedIssue


class ReproVerdict(StrEnum):
    """The outcome of attempting to reproduce a reported bug."""

    REPRODUCED = "reproduced"
    COULD_NOT_REPRODUCE = "could_not_reproduce"
    NEEDS_INFO = "needs_info"


class RouteTarget(StrEnum):
    """Where triage routes an issue after classification."""

    BUG = "bug"
    NON_BUG = "non_bug"
    NEEDS_INFO = "needs_info"


class GraphOutcome(StrEnum):
    """The terminal disposition of one run, for reporting and the audit trail."""

    PENDING = "pending"
    TRIAGED_NON_BUG = "triaged_non_bug"
    NEEDS_INFO = "needs_info"
    COULD_NOT_REPRODUCE = "could_not_reproduce"
    FIX_PROPOSED = "fix_proposed"
    GAVE_UP = "gave_up"


class ReproOutcome(BaseModel):
    """A reproduction verdict and the evidence behind it.

    ``evidence`` is the sandboxed test run that demonstrated the bug (a failing
    test). A ``REPRODUCED`` verdict without evidence is a contradiction the
    graph never constructs.
    """

    model_config = ConfigDict(frozen=True)

    verdict: ReproVerdict
    summary: str
    evidence: SandboxResult | None = None


class ProposedPatch(BaseModel):
    """A candidate fix plus the test that is meant to prove it (lands fully in #15)."""

    model_config = ConfigDict(frozen=True)

    diff: str = Field(min_length=1)
    proof_test: str = Field(min_length=1)
    rationale: str = ""


class OpenedPR(BaseModel):
    """A reference to the draft PR opened for a verified fix (lands fully in #16)."""

    model_config = ConfigDict(frozen=True)

    branch: str
    title: str
    draft: bool = True
    number: int | None = None
    url: str | None = None


class GraphState(BaseModel):
    """The single state object threaded through the agent graph.

    ``attempts`` counts completed patch→test cycles; the graph backtracks to
    hypothesize while it stays below ``max_attempts`` and a proof test is still
    failing. ``notes`` accumulates a human-readable trail across nodes (an
    additive reducer), useful for the dashboard and the audit log.
    """

    issue: NormalizedIssue
    trace_id: str
    max_attempts: int = Field(default=2, ge=1)

    triage: TriageDecision | None = None
    route: RouteTarget | None = None
    repro: ReproOutcome | None = None
    hypothesis: str | None = None
    patch: ProposedPatch | None = None
    test_result: SandboxResult | None = None
    attempts: int = 0
    verified: bool = False
    pr: OpenedPR | None = None
    outcome: GraphOutcome = GraphOutcome.PENDING
    notes: Annotated[list[str], operator.add] = Field(default_factory=list)
