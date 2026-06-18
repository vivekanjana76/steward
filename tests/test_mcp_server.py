"""Tests for the Steward MCP server (issue #17).

Each tool is exercised end-to-end through FastMCP's in-memory client (the real
tool dispatch, no transport/process) with the capabilities stubbed by fakes, so
the handler logic, schemas, and policy routing are asserted deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastmcp import Client

from steward.graph.state import GraphState, ProposedPatch
from steward.mcp.schemas import CodeHit
from steward.mcp.server import build_server
from steward.mcp.service import StewardTools
from steward.policy.engine import PolicyEngine
from steward.review.offline import build_offline_council
from steward.sandbox import SandboxRunner, SandboxSpec
from steward.sandbox.runner import ContainerRun
from steward.triage.dedup import DuplicateCandidate, DuplicateReport
from steward.triage.models import IssueState, NormalizedIssue

TARGET = "stewardbot/demo-shop"


def _issue(number: int = 128) -> NormalizedIssue:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    return NormalizedIssue(
        number=number,
        title="Checkout total ignores discount",
        body="Applying a code does not reduce the total.",
        state=IssueState.OPEN,
        labels=("type:bug",),
        created_at=now,
        updated_at=now,
        injection_signals=("ignore-previous-instructions",),
    )


class FakeIssues:
    def get_issue(self, number: int) -> NormalizedIssue:
        return _issue(number)


class FakeDedup:
    def find_duplicates(self, issue: NormalizedIssue) -> DuplicateReport:
        return DuplicateReport(
            issue_number=issue.number,
            candidates=(DuplicateCandidate(issue_number=99, title="dup", score=0.91),),
            threshold=0.85,
            embedding_model="voyage-3",
        )


class FakeSearch:
    def search(self, query: str, *, limit: int) -> list[CodeHit]:
        return [CodeHit(path="shop/checkout.py", line=42, snippet=f"# {query}")]


class FakePatcher:
    def propose(self, state: GraphState) -> ProposedPatch:
        return ProposedPatch(
            diff="--- a/x\n+++ b/x", proof_test="def test(): ...", rationale="fix it"
        )


class PassBackend:
    def run(self, spec: SandboxSpec) -> ContainerRun:
        return ContainerRun(exit_code=0, stdout="2 passed", stderr="", timed_out=False)


def _data(res: object) -> dict:
    content = getattr(res, "structured_content", None)
    assert isinstance(content, dict)
    return content


def _server(*, runner: SandboxRunner | None = None):
    tools = StewardTools(
        policy_engine=PolicyEngine(target_repo=TARGET),
        issue_provider=FakeIssues(),
        duplicate_finder=FakeDedup(),
        code_searcher=FakeSearch(),
        patch_proposer=FakePatcher(),
        patch_reviewer=build_offline_council(),
        sandbox_runner=runner or SandboxRunner(PassBackend()),
    )
    return build_server(tools)


async def test_lists_all_tools() -> None:
    async with Client(_server()) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {
        "get_issue_context",
        "find_duplicate_issues",
        "search_codebase",
        "run_repo_tests_sandboxed",
        "propose_patch",
        "review_patch",
    }


async def test_get_issue_context_surfaces_injection_signals() -> None:
    async with Client(_server()) as client:
        res = await client.call_tool("get_issue_context", {"issue_number": 128})
    data = _data(res)
    assert data["number"] == 128
    assert data["labels"] == ["type:bug"]
    assert data["has_injection_signals"] is True


async def test_find_duplicate_issues_returns_scored_candidates() -> None:
    async with Client(_server()) as client:
        res = await client.call_tool("find_duplicate_issues", {"issue_number": 128})
    data = _data(res)
    assert data["candidates"][0]["issue_number"] == 99
    assert data["candidates"][0]["score"] == pytest.approx(0.91)


async def test_search_codebase_returns_located_hits() -> None:
    async with Client(_server()) as client:
        res = await client.call_tool("search_codebase", {"query": "discount", "limit": 5})
    data = _data(res)
    assert data["hits"][0]["path"] == "shop/checkout.py"
    assert data["hits"][0]["line"] == 42


async def test_propose_patch_returns_diff_and_proof() -> None:
    async with Client(_server()) as client:
        res = await client.call_tool(
            "propose_patch", {"issue_number": 128, "hypothesis": "wrong order"}
        )
    data = _data(res)
    assert data["diff"].startswith("--- a/x")
    assert data["proof_test"]


async def test_review_patch_blocks_a_dangerous_diff() -> None:
    # The security reviewer blocks a diff that introduces a shell-out sink, and
    # the council returns that as the aggregate verdict with a grounded citation.
    diff = "--- a/x\n+++ b/x\n+    os.system(user_input)\n"
    async with Client(_server()) as client:
        res = await client.call_tool("review_patch", {"diff": diff, "proof_test": "assert run()"})
    data = _data(res)
    assert data["verdict"] == 2  # ReviewVerdict.BLOCK
    assert any(f["dimension"] == "security" and f["citation"] for f in data["findings"])


async def test_review_patch_approves_a_clean_diff() -> None:
    diff = "--- a/x\n+++ b/x\n+    return subtotal - discount\n"
    async with Client(_server()) as client:
        res = await client.call_tool(
            "review_patch",
            {"diff": diff, "proof_test": "def test():\n    assert f() == 90", "test_passed": True},
        )
    data = _data(res)
    assert data["verdict"] == 0  # ReviewVerdict.APPROVE


async def test_run_repo_tests_sandboxed_passes_for_target_repo() -> None:
    async with Client(_server()) as client:
        res = await client.call_tool(
            "run_repo_tests_sandboxed",
            {"repo": TARGET, "repo_path": ".", "command": "pytest -q"},
        )
    data = _data(res)
    assert data["passed"] is True
    assert data["stdout_tail"] == "2 passed"


async def test_run_repo_tests_sandboxed_denies_off_target_repo() -> None:
    # Routed through the policy engine: a repo other than the target is refused.
    async with Client(_server()) as client:
        with pytest.raises(Exception) as exc:
            await client.call_tool(
                "run_repo_tests_sandboxed",
                {"repo": "someone/else", "repo_path": ".", "command": "pytest -q"},
            )
    assert "someone/else" in str(exc.value) or "denied" in str(exc.value).lower()


def test_facade_run_tests_maps_sandbox_result() -> None:
    # The facade truncates logs and maps the SandboxResult faithfully.
    class BigLogBackend:
        def run(self, spec: SandboxSpec) -> ContainerRun:
            return ContainerRun(exit_code=1, stdout="x" * 5000, stderr="boom", timed_out=False)

    tools = StewardTools(
        policy_engine=PolicyEngine(target_repo=TARGET),
        issue_provider=FakeIssues(),
        duplicate_finder=FakeDedup(),
        code_searcher=FakeSearch(),
        patch_proposer=FakePatcher(),
        patch_reviewer=build_offline_council(),
        sandbox_runner=SandboxRunner(BigLogBackend()),
    )
    report = tools.run_repo_tests_sandboxed(TARGET, ".", "pytest")
    assert report.passed is False
    assert report.exit_code == 1
    assert len(report.stdout_tail) == 4000  # tail-truncated
