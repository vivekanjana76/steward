"""Deterministic, keyless reviewers so the council runs in CI, the demo, and evals.

These mirror the LLM specialists' *contract* (one :class:`ReviewFinding` per
dimension) with simple, general heuristics over the diff — not tuned to any eval
set, so the baseline they produce is an honest measurement of a deterministic
reference rather than a faked perfect score (mirrors
:mod:`steward.evals.offline`). They are grounded: every non-approval cites the
exact line that triggered it.
"""

from __future__ import annotations

import re

from steward.review.council import ReviewCouncil
from steward.review.models import ReviewContext, ReviewDimension, ReviewFinding, ReviewVerdict

# Security sinks introduced by a diff that should block a fix outright.
_SECURITY_SINKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\beval\s*\("), "use of eval()"),
    (re.compile(r"\bexec\s*\("), "use of exec()"),
    (re.compile(r"os\.system\s*\("), "shell-out via os.system()"),
    (re.compile(r"shell\s*=\s*True"), "subprocess with shell=True"),
    (re.compile(r"pickle\.loads\s*\("), "unsafe pickle.loads()"),
    (re.compile(r"verify\s*=\s*False"), "TLS verification disabled"),
    (
        re.compile(r"""(?i)(password|secret|api_key|token)\s*=\s*['"][^'"]+['"]"""),
        "hardcoded secret",
    ),
)

# Markers of debugging/scaffolding that shouldn't ship in a fix.
_DEBUG_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bbreakpoint\s*\("), "leftover breakpoint()"),
    (re.compile(r"import\s+pdb\b"), "leftover pdb import"),
    (re.compile(r"\bprint\s*\("), "leftover print() debugging"),
    (re.compile(r"#\s*TODO\b"), "unresolved TODO in the fix"),
)

_ASSERT_RE = re.compile(r"\b(assert|self\.assert\w+|pytest\.raises|expect\()")


class OfflineCorrectnessReviewer:
    """Flags empty diffs, missing rationale, and obvious debug leftovers."""

    dimension = ReviewDimension.CORRECTNESS

    def review(self, context: ReviewContext) -> ReviewFinding:
        added = context.added_lines()
        code = [ln for ln in added if ln.strip() and not ln.lstrip().startswith("#")]
        if not code:
            return ReviewFinding(
                dimension=self.dimension,
                verdict=ReviewVerdict.REQUEST_CHANGES,
                rationale="the diff changes no code, so it cannot fix the bug",
                citation=added[0] if added else "(empty diff)",
            )
        for line in added:
            for pattern, why in _DEBUG_MARKERS:
                if pattern.search(line):
                    return ReviewFinding(
                        dimension=self.dimension,
                        verdict=ReviewVerdict.REQUEST_CHANGES,
                        rationale=f"remove debugging/scaffolding before proposing the fix: {why}",
                        citation=line.strip(),
                    )
        return ReviewFinding(
            dimension=self.dimension,
            verdict=ReviewVerdict.APPROVE,
            rationale="diff makes a focused code change with no debug leftovers",
        )


class OfflineSecurityReviewer:
    """Blocks a fix that introduces a known dangerous sink or a hardcoded secret."""

    dimension = ReviewDimension.SECURITY

    def review(self, context: ReviewContext) -> ReviewFinding:
        for line in context.added_lines():
            for pattern, why in _SECURITY_SINKS:
                if pattern.search(line):
                    return ReviewFinding(
                        dimension=self.dimension,
                        verdict=ReviewVerdict.BLOCK,
                        rationale=f"the fix introduces a security risk: {why}",
                        citation=line.strip(),
                    )
        return ReviewFinding(
            dimension=self.dimension,
            verdict=ReviewVerdict.APPROVE,
            rationale="no dangerous sinks or secrets introduced by the diff",
        )


class OfflineTestQualityReviewer:
    """Requires a real, asserting proof test that actually passed."""

    dimension = ReviewDimension.TEST_QUALITY

    def review(self, context: ReviewContext) -> ReviewFinding:
        test = context.proof_test.strip()
        if not test:
            return ReviewFinding(
                dimension=self.dimension,
                verdict=ReviewVerdict.REQUEST_CHANGES,
                rationale="no proof test accompanies the fix",
                citation="(no proof test)",
            )
        if not _ASSERT_RE.search(test):
            return ReviewFinding(
                dimension=self.dimension,
                verdict=ReviewVerdict.REQUEST_CHANGES,
                rationale="the proof test asserts nothing, so it proves nothing",
                citation=test.splitlines()[-1].strip(),
            )
        if not context.test_passed:
            return ReviewFinding(
                dimension=self.dimension,
                verdict=ReviewVerdict.REQUEST_CHANGES,
                rationale="the proof test did not pass in the sandbox",
                citation="(proof test failed)",
            )
        return ReviewFinding(
            dimension=self.dimension,
            verdict=ReviewVerdict.APPROVE,
            rationale="proof test asserts the fixed behavior and passed in the sandbox",
        )


def build_offline_council() -> ReviewCouncil:
    """A three-seat council of the deterministic reviewers (no keys required)."""
    return ReviewCouncil(
        [
            OfflineCorrectnessReviewer(),
            OfflineSecurityReviewer(),
            OfflineTestQualityReviewer(),
        ]
    )
