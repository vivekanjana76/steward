"""MCP contract tests for the Steward server (issue #18).

These guard the **product surface** so it can't silently drift (CLAUDE.md §9):

* every tool declares an input and output schema and a cold-agent description;
* each tool's returned payload validates against its **declared Pydantic output
  model** (a round-trip), so the wire schema and the model can't diverge;
* the exposed tool set is exactly the read-only / sandboxed five — **no
  world-mutating tool is exposed**, and the one acting tool honors the policy
  engine (an off-target repo is denied).

Fixtures are stubbed; no live network or Docker. These run in CI with the suite.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastmcp import Client
from pydantic import BaseModel

from steward.graph.state import GraphState, ProposedPatch
from steward.mcp.schemas import CodeHit, CodeSearchResults, IssueContext, SandboxTestReport
from steward.mcp.server import build_server
from steward.mcp.service import StewardTools
from steward.policy.engine import ActionKind, PolicyEngine, PolicyList, list_for
from steward.sandbox import SandboxRunner, SandboxSpec
from steward.sandbox.runner import ContainerRun
from steward.triage.dedup import DuplicateCandidate, DuplicateReport
from steward.triage.models import IssueState, NormalizedIssue

TARGET = "stewardbot/demo-shop"

# Each tool and the Pydantic model its result must validate against.
_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "get_issue_context": IssueContext,
    "find_duplicate_issues": DuplicateReport,
    "search_codebase": CodeSearchResults,
    "run_repo_tests_sandboxed": SandboxTestReport,
    "propose_patch": ProposedPatch,
}

# A valid arguments set for each tool, for the round-trip checks.
_CALL_ARGS: dict[str, dict[str, object]] = {
    "get_issue_context": {"issue_number": 1},
    "find_duplicate_issues": {"issue_number": 1},
    "search_codebase": {"query": "x"},
    "run_repo_tests_sandboxed": {"repo": TARGET, "repo_path": ".", "command": "pytest"},
    "propose_patch": {"issue_number": 1, "hypothesis": "h"},
}


def _issue(number: int = 1) -> NormalizedIssue:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    return NormalizedIssue(
        number=number, title="t", body="b", state=IssueState.OPEN, created_at=now, updated_at=now
    )


class _FakeIssues:
    def get_issue(self, number: int) -> NormalizedIssue:
        return _issue(number)


class _FakeDedup:
    def find_duplicates(self, issue: NormalizedIssue) -> DuplicateReport:
        return DuplicateReport(
            issue_number=issue.number,
            candidates=(DuplicateCandidate(issue_number=2, title="d", score=0.9),),
            threshold=0.85,
            embedding_model="voyage-3",
        )


class _FakeSearch:
    def search(self, query: str, *, limit: int) -> list[CodeHit]:
        return [CodeHit(path="p.py", line=1, snippet=query)]


class _FakePatcher:
    def propose(self, state: GraphState) -> ProposedPatch:
        return ProposedPatch(diff="--- a\n+++ b", proof_test="t")


class _PassBackend:
    def run(self, spec: SandboxSpec) -> ContainerRun:
        return ContainerRun(exit_code=0, stdout="ok", stderr="", timed_out=False)


def _server():
    return build_server(
        StewardTools(
            policy_engine=PolicyEngine(target_repo=TARGET),
            issue_provider=_FakeIssues(),
            duplicate_finder=_FakeDedup(),
            code_searcher=_FakeSearch(),
            patch_proposer=_FakePatcher(),
            sandbox_runner=SandboxRunner(_PassBackend()),
        )
    )


async def test_every_tool_declares_schemas_and_a_description() -> None:
    async with Client(_server()) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == set(_OUTPUT_MODELS)
    for tool in tools:
        assert tool.description and len(tool.description.strip()) > 20, tool.name
        assert tool.inputSchema.get("type") == "object"
        assert tool.outputSchema is not None, tool.name


@pytest.mark.parametrize("tool_name", sorted(_OUTPUT_MODELS))
async def test_tool_output_validates_against_declared_model(tool_name: str) -> None:
    model = _OUTPUT_MODELS[tool_name]
    async with Client(_server()) as client:
        result = await client.call_tool(tool_name, _CALL_ARGS[tool_name])
    # The wire payload must validate cleanly against the declared output model.
    assert result.structured_content is not None
    model.model_validate(result.structured_content)


async def test_no_world_mutating_tool_is_exposed() -> None:
    # Mutations (comment/label/branch/PR/merge) stay behind the approval queue;
    # the MCP surface must expose none of them.
    mutating = {kind.value for kind in ActionKind if list_for(kind) is not PolicyList.WHITELIST}
    async with Client(_server()) as client:
        names = {t.name for t in await client.list_tools()}
    assert names.isdisjoint(mutating)


async def test_required_inputs_are_declared() -> None:
    async with Client(_server()) as client:
        by_name = {t.name: t for t in await client.list_tools()}
    assert set(by_name["run_repo_tests_sandboxed"].inputSchema["required"]) == {
        "repo",
        "repo_path",
        "command",
    }
    assert "hypothesis" in by_name["propose_patch"].inputSchema["required"]


async def test_acting_tool_honors_policy_off_target() -> None:
    async with Client(_server()) as client:
        with pytest.raises(Exception) as exc:
            await client.call_tool(
                "run_repo_tests_sandboxed",
                {"repo": "other/repo", "repo_path": ".", "command": "pytest"},
            )
    assert "other/repo" in str(exc.value) or "denied" in str(exc.value).lower()
