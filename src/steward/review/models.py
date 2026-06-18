"""Typed contracts for the multi-agent reviewer council (issue #55).

A council review is the last grounded gate before a draft PR is proposed. Each
specialist reviewer returns a :class:`ReviewFinding` for its dimension, and a
supervisor aggregates them into one :class:`CouncilReview`. The aggregation is
**conservative**: the worst verdict any reviewer raises wins, so a single
security block stops the PR even if every other dimension approves (CLAUDE.md
§1/§3).

This module depends only on :mod:`steward.triage.models` (a leaf), so it can be
imported from :mod:`steward.graph.state` without a cycle.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum

from pydantic import BaseModel, ConfigDict, Field

from steward.triage.models import NormalizedIssue


class ReviewDimension(str):
    """A namespace of the axes the council reviews along (string-valued).

    Kept as plain string constants rather than an enum so a finding's
    ``dimension`` is open for new reviewers without a schema migration; the three
    shipped dimensions are the well-known values below.
    """

    CORRECTNESS = "correctness"
    SECURITY = "security"
    TEST_QUALITY = "test_quality"


class ReviewVerdict(IntEnum):
    """A single reviewer's (or the council's) verdict, ordered by severity.

    The integer ordering *is* the aggregation rule — the council's verdict is the
    maximum (most severe) over its findings — so ``APPROVE < REQUEST_CHANGES <
    BLOCK`` must hold.
    """

    APPROVE = 0
    REQUEST_CHANGES = 1
    BLOCK = 2

    @property
    def label(self) -> str:
        """The lowercase wire/display name (e.g. ``"request_changes"``)."""
        return self.name.lower()


class ReviewFinding(BaseModel):
    """One specialist reviewer's grounded verdict on one dimension.

    ``citation`` anchors the finding in the patch under review — a line from the
    diff or the proof test — so the verdict is evidence-bearing, never an unbacked
    opinion (CLAUDE.md §1). It may be empty only for an ``APPROVE`` (nothing to
    point at).
    """

    model_config = ConfigDict(frozen=True)

    dimension: str = Field(min_length=1)
    verdict: ReviewVerdict
    rationale: str = Field(min_length=1)
    citation: str = ""


class CouncilReview(BaseModel):
    """The supervisor's aggregate of every reviewer's finding.

    ``verdict`` is the most severe finding; ``approved`` is the convenience the
    graph and the MCP tool gate on. ``findings`` is kept in full so the decision
    is replayable and the dashboard can show who objected and why.
    """

    model_config = ConfigDict(frozen=True)

    verdict: ReviewVerdict
    summary: str
    findings: tuple[ReviewFinding, ...] = ()

    @property
    def approved(self) -> bool:
        """True when no reviewer asked for changes or blocked."""
        return self.verdict is ReviewVerdict.APPROVE

    @classmethod
    def aggregate(cls, findings: Sequence[ReviewFinding]) -> CouncilReview:
        """Combine ``findings`` into one review (worst verdict wins)."""
        if not findings:
            return cls(verdict=ReviewVerdict.APPROVE, summary="no findings; approved", findings=())
        verdict = max(f.verdict for f in findings)
        objectors = [f for f in findings if f.verdict is not ReviewVerdict.APPROVE]
        if verdict is ReviewVerdict.APPROVE:
            summary = f"approved by all {len(findings)} reviewer(s)"
        else:
            dims = ", ".join(f"{f.dimension} ({f.verdict.label})" for f in objectors)
            summary = f"{verdict.label} — raised by {dims}"
        return cls(verdict=verdict, summary=summary, findings=tuple(findings))

    @classmethod
    def unanimous_approve(cls, summary: str) -> CouncilReview:
        """An empty-panel approval (used when no council is configured)."""
        return cls(verdict=ReviewVerdict.APPROVE, summary=summary, findings=())


class ReviewContext(BaseModel):
    """Everything a reviewer needs to judge a proposed fix.

    The patch is carried as plain strings (``diff`` / ``proof_test``) rather than
    a ``ProposedPatch`` so this module stays free of a ``graph.state`` import.
    Reviewers must treat the issue and diff text as **untrusted data**, never as
    instructions (CLAUDE.md §5).
    """

    model_config = ConfigDict(frozen=True)

    issue: NormalizedIssue | None = None
    diff: str = Field(min_length=1)
    proof_test: str = ""
    proof_test_path: str = ""
    hypothesis: str = ""
    repro_summary: str = ""
    test_passed: bool = False

    def added_lines(self) -> list[str]:
        """The lines the diff *adds* (``+`` prefix, excluding the ``+++`` header)."""
        return [
            line[1:]
            for line in self.diff.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
