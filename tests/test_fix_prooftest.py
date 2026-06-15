"""Tests for the sandbox proof tester (issue #15).

Unit layer: a real :class:`SandboxRunner` driven by a fake backend that inspects
the materialized work tree, so the fail-before / pass-after logic is asserted
deterministically with no Docker. Integration layer (gated by
``STEWARD_SANDBOX_IT`` + a daemon): a real fail→pass on a tiny fixture repo.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from steward.fix.prooftest import SandboxProofTester
from steward.graph.state import GraphState, ProposedPatch
from steward.sandbox import SandboxRunner, SandboxSpec
from steward.sandbox.runner import ContainerRun
from steward.triage.models import IssueState, NormalizedIssue

_BUGGY = "def add(a, b):\n    return a - b\n"

_FIX = (
    "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n-    return a - b\n+    return a + b\n"
)
_PROOF = (
    "import unittest\nfrom calc import add\n\n"
    "class T(unittest.TestCase):\n"
    "    def test_add(self):\n"
    "        self.assertEqual(add(1, 1), 2)\n"
)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text(_BUGGY, encoding="utf-8")
    return repo


def _state(patch: ProposedPatch) -> GraphState:
    now = datetime(2026, 6, 15, tzinfo=UTC)
    issue = NormalizedIssue(
        number=1,
        title="add subtracts",
        body="bug",
        state=IssueState.OPEN,
        created_at=now,
        updated_at=now,
    )
    return GraphState(issue=issue, trace_id="t", patch=patch)


class FixDetectingBackend:
    """Passes only when the work tree has the fix applied and the proof present."""

    def __init__(self) -> None:
        self.seen: list[bool] = []  # whether each run saw the fix applied

    def run(self, spec: SandboxSpec) -> ContainerRun:
        calc = (spec.repo_path / "calc.py").read_text(encoding="utf-8")
        proof_present = (spec.repo_path / "test_steward_proof.py").exists()
        fixed = "a + b" in calc
        self.seen.append(fixed)
        passed = fixed and proof_present
        return ContainerRun(exit_code=0 if passed else 1, stdout="", stderr="", timed_out=False)


class AlwaysPassBackend:
    def run(self, spec: SandboxSpec) -> ContainerRun:
        return ContainerRun(exit_code=0, stdout="", stderr="", timed_out=False)


def test_genuine_fail_then_pass_is_proven(tmp_path: Path) -> None:
    backend = FixDetectingBackend()
    tester = SandboxProofTester(SandboxRunner(backend), _repo(tmp_path))
    result = tester.run_proof(_state(ProposedPatch(diff=_FIX, proof_test=_PROOF)))
    assert result.passed is True
    # Ran twice: unpatched (no fix) then patched (fix present).
    assert backend.seen == [False, True]


def test_host_repo_is_never_mutated(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    tester = SandboxProofTester(SandboxRunner(FixDetectingBackend()), repo)
    tester.run_proof(_state(ProposedPatch(diff=_FIX, proof_test=_PROOF)))
    assert (repo / "calc.py").read_text(encoding="utf-8") == _BUGGY  # untouched


def test_proof_that_passes_unpatched_is_rejected(tmp_path: Path) -> None:
    # If the proof test passes even without the fix, it proves nothing.
    tester = SandboxProofTester(SandboxRunner(AlwaysPassBackend()), _repo(tmp_path))
    result = tester.run_proof(_state(ProposedPatch(diff=_FIX, proof_test=_PROOF)))
    assert result.passed is False
    assert "proof invalid" in result.stderr


def _docker_available() -> bool:
    try:
        import docker  # type: ignore[import-untyped]

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    os.environ.get("STEWARD_SANDBOX_IT") != "1" or not _docker_available(),
    reason="integration test: set STEWARD_SANDBOX_IT=1 and run a reachable Docker daemon",
)
def test_integration_real_fail_then_pass(tmp_path: Path) -> None:
    from steward.sandbox.docker_backend import DockerBackend

    tester = SandboxProofTester(SandboxRunner(DockerBackend()), _repo(tmp_path), timeout_s=600)
    result = tester.run_proof(_state(ProposedPatch(diff=_FIX, proof_test=_PROOF)))
    assert result.passed is True, result.stdout + result.stderr
