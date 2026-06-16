"""Output schemas for the Steward MCP server's tools (product surface, §14).

These are part of the product: a cold agent reads these shapes to know what each
tool returns. They reuse Steward's existing typed contracts where those already
make good surface (``DuplicateReport``, ``ProposedPatch``) and add MCP-specific
views (issue context, code hits, a truncated sandbox report) elsewhere.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from steward.triage.models import NormalizedIssue

# Logs can be large; the MCP report carries only the tail so a tool result stays
# token-cheap. Full logs live in the trace.
_LOG_TAIL_CHARS = 4000


class IssueContext(BaseModel):
    """A compact, grounded snapshot of one issue for an agent to reason over.

    All free text is already sanitized at ingestion; ``injection_signals`` flags
    any prompt-injection heuristics that fired, so a consumer can stay cautious.
    """

    model_config = ConfigDict(frozen=True)

    number: int
    title: str
    body: str
    state: str
    labels: list[str] = Field(default_factory=list)
    comment_count: int = 0
    injection_signals: list[str] = Field(default_factory=list)
    has_injection_signals: bool = False

    @classmethod
    def from_issue(cls, issue: NormalizedIssue) -> IssueContext:
        """Project a :class:`NormalizedIssue` onto the agent-facing context."""
        return cls(
            number=issue.number,
            title=issue.title,
            body=issue.body,
            state=issue.state.value,
            labels=list(issue.labels),
            comment_count=len(issue.comments),
            injection_signals=list(issue.injection_signals),
            has_injection_signals=issue.has_injection_signals,
        )


class CodeHit(BaseModel):
    """One code-search match: where it is and the matching snippet."""

    model_config = ConfigDict(frozen=True)

    path: str
    line: int
    snippet: str


class CodeSearchResults(BaseModel):
    """The grounded result of a codebase search — only real, located matches."""

    model_config = ConfigDict(frozen=True)

    query: str
    hits: list[CodeHit] = Field(default_factory=list)


class SandboxTestReport(BaseModel):
    """The verdict of a sandboxed test run, with truncated logs.

    ``passed`` is the single source of truth (a clean exit within the timeout).
    Logs are tail-truncated to keep the tool result small; the full run is in the
    trace.
    """

    model_config = ConfigDict(frozen=True)

    passed: bool
    exit_code: int | None
    timed_out: bool
    duration_s: float
    image: str
    command: str
    stdout_tail: str
    stderr_tail: str

    @staticmethod
    def tail(text: str) -> str:
        """Return the last chunk of ``text`` (the part that usually matters)."""
        return text[-_LOG_TAIL_CHARS:] if len(text) > _LOG_TAIL_CHARS else text
