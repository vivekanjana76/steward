"""The capability facade behind the MCP tools.

The MCP tool functions are thin wrappers; this facade holds the logic and the
collaborators, so the tools are testable without a transport and the side-
effect/policy rules live in one place. Collaborators are injected as protocols,
so a test supplies fakes and the default server wires real implementations (or
clearly-unavailable stubs where a key/checkout is required).

Policy posture: the only tool here that *acts* — running tests — does so in a
disposable sandbox, which is a **whitelist** ``RUN_SANDBOXED_TESTS`` action; it
is still routed through the policy engine (``authorize``) so an off-target repo
is denied. World-mutating actions (commenting, opening PRs) are deliberately
**not** exposed as MCP tools: those stay behind the human approval queue
(CLAUDE.md §5/§14).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from steward.graph.state import GraphState, ProposedPatch
from steward.mcp.schemas import CodeHit, CodeSearchResults, IssueContext, SandboxTestReport
from steward.observability import new_trace_id
from steward.policy.engine import Action, ActionKind, PolicyEngine
from steward.review.council import PatchReviewer
from steward.review.models import CouncilReview, ReviewContext
from steward.sandbox import SandboxRunner, SandboxSpec
from steward.triage.dedup import DuplicateReport
from steward.triage.models import NormalizedIssue


class CapabilityUnavailable(RuntimeError):
    """Raised by a tool whose backing capability is not configured/wired."""


class IssueProvider(Protocol):
    """Fetches a normalized issue by number (e.g. from GitHub, sanitized)."""

    def get_issue(self, number: int) -> NormalizedIssue: ...


class DuplicateFinder(Protocol):
    """Finds likely-duplicate issues for a given issue (the dedup detector)."""

    def find_duplicates(self, issue: NormalizedIssue) -> DuplicateReport: ...


class CodeSearcher(Protocol):
    """Searches the repository's code for a query, returning located hits."""

    def search(self, query: str, *, limit: int) -> list[CodeHit]: ...


class PatchProposer(Protocol):
    """Proposes a patch + proof test for a hypothesis (the patch generator)."""

    def propose(self, state: GraphState) -> ProposedPatch: ...


class StewardTools:
    """Implements every MCP tool's logic over injected capabilities."""

    def __init__(
        self,
        *,
        policy_engine: PolicyEngine,
        issue_provider: IssueProvider,
        duplicate_finder: DuplicateFinder,
        code_searcher: CodeSearcher,
        patch_proposer: PatchProposer,
        patch_reviewer: PatchReviewer,
        sandbox_runner: SandboxRunner,
        sandbox_image: str = "python:3.12-slim",
    ) -> None:
        self._engine = policy_engine
        self._issues = issue_provider
        self._dedup = duplicate_finder
        self._search = code_searcher
        self._patcher = patch_proposer
        self._reviewer = patch_reviewer
        self._sandbox = sandbox_runner
        self._image = sandbox_image

    def get_issue_context(self, issue_number: int) -> IssueContext:
        return IssueContext.from_issue(self._issues.get_issue(issue_number))

    def find_duplicate_issues(self, issue_number: int) -> DuplicateReport:
        issue = self._issues.get_issue(issue_number)
        return self._dedup.find_duplicates(issue)

    def search_codebase(self, query: str, limit: int = 10) -> CodeSearchResults:
        hits = self._search.search(query, limit=max(1, min(limit, 100)))
        return CodeSearchResults(query=query, hits=hits)

    def propose_patch(self, issue_number: int, hypothesis: str) -> ProposedPatch:
        issue = self._issues.get_issue(issue_number)
        state = GraphState(issue=issue, trace_id=new_trace_id(), hypothesis=hypothesis)
        return self._patcher.propose(state)

    def review_patch(
        self,
        diff: str,
        proof_test: str = "",
        hypothesis: str = "",
        proof_test_path: str = "",
        test_passed: bool = True,
    ) -> CouncilReview:
        """Run the multi-agent review council over a candidate patch.

        Read-only reasoning — it inspects the supplied diff/test and returns a
        grounded verdict; it never applies or commits anything. No policy gate is
        needed because nothing is mutated.
        """
        context = ReviewContext(
            diff=diff,
            proof_test=proof_test,
            proof_test_path=proof_test_path,
            hypothesis=hypothesis,
            test_passed=test_passed,
        )
        return self._reviewer.review(context)

    def run_repo_tests_sandboxed(
        self, repo: str, repo_path: str, command: str, *, image: str | None = None
    ) -> SandboxTestReport:
        """Run a repo's tests in a disposable sandbox, routed through policy.

        The run is expressed as a ``RUN_SANDBOXED_TESTS`` action and
        ``authorize``d first: the engine raises for a repo other than its
        configured target, so this tool can never run tests for a repo Steward
        isn't scoped to.
        """
        action = Action(
            kind=ActionKind.RUN_SANDBOXED_TESTS,
            repo=repo,
            summary=f"Run sandboxed tests for {repo}: {command}",
        )
        self._engine.authorize(action)  # raises PolicyViolationError off-target
        spec = SandboxSpec(image=image or self._image, command=command, repo_path=Path(repo_path))
        result = self._sandbox.run_tests(spec)
        return SandboxTestReport(
            passed=result.passed,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            duration_s=result.duration_s,
            image=result.image,
            command=result.command,
            stdout_tail=SandboxTestReport.tail(result.stdout),
            stderr_tail=SandboxTestReport.tail(result.stderr),
        )


def _unavailable(name: str, hint: str) -> CapabilityUnavailable:
    return CapabilityUnavailable(f"the '{name}' capability is not configured: {hint}")


class _UnavailableIssues:
    def get_issue(self, number: int) -> NormalizedIssue:
        raise _unavailable("get_issue_context", "wire an issue source (GitHub token)")


class _UnavailableDedup:
    def find_duplicates(self, issue: NormalizedIssue) -> DuplicateReport:
        raise _unavailable("find_duplicate_issues", "configure embeddings (VOYAGE_API_KEY)")


class _UnavailableSearch:
    def search(self, query: str, *, limit: int) -> list[CodeHit]:
        raise _unavailable("search_codebase", "point the server at a repo checkout")


class _UnavailablePatcher:
    def propose(self, state: GraphState) -> ProposedPatch:
        raise _unavailable("propose_patch", "configure the model client (ANTHROPIC_API_KEY)")
