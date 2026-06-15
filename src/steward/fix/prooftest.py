"""Prove a patch in the sandbox: the test must fail before and pass after.

A proof test is only evidence if it actually *fails on the unpatched code and
passes once the fix is applied* (CLAUDE.md §1). :class:`SandboxProofTester`
establishes exactly that: it materializes a throwaway copy of the repo, runs the
proof test **unpatched** (expecting failure), then runs it again with the diff
applied (expecting success). The verdict it returns is ``passed`` only when both
hold — a proof test that already passes without the fix proves nothing and is
rejected.

This implements the graph's :class:`~steward.graph.capabilities.Tester` seam;
the host checkout is never mutated (all work happens in temp copies, then in the
sandbox container).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from steward.fix.patch import apply_patch, patched_paths
from steward.graph.state import GraphState, ProposedPatch
from steward.sandbox import SandboxResult, SandboxRunner, SandboxSpec

# Default proof command: stdlib unittest (no network needed in the sandbox),
# matching the proof test by filename. ``{proof_name}`` is the file's basename.
DEFAULT_PROOF_COMMAND = "python -m unittest discover -p '{proof_name}'"


class SandboxProofTester:
    """Runs a candidate patch's proof test before and after applying the diff.

    ``repo_path`` is a checkout of the repo under test; ``image`` and
    ``test_command`` configure the sandbox run. ``test_command`` may reference
    ``{proof_name}`` (the proof test's basename) and ``{proof}`` (its repo path).
    """

    def __init__(
        self,
        runner: SandboxRunner,
        repo_path: Path,
        *,
        image: str = "python:3.12-slim",
        test_command: str = DEFAULT_PROOF_COMMAND,
        timeout_s: float = 300.0,
    ) -> None:
        self._runner = runner
        self._repo_path = repo_path
        self._image = image
        self._test_command = test_command
        self._timeout_s = timeout_s

    def run_proof(self, state: GraphState) -> SandboxResult:
        """Return the proof verdict: ``passed`` only on a genuine fail→pass."""
        patch = state.patch
        if patch is None:  # pragma: no cover - the graph only tests after patch
            raise ValueError("run_proof called with no proposed patch in state")

        before = self._run_variant(patch, apply_fix=False, trace_id=state.trace_id)
        failed_before = not before.passed
        after = self._run_variant(patch, apply_fix=True, trace_id=state.trace_id)

        proven = failed_before and after.passed
        if proven:
            return after
        note = f"[proof invalid: failed_before={failed_before}, after_passed={after.passed}] "
        return after.model_copy(update={"passed": False, "stderr": note + after.stderr})

    def _run_variant(
        self, patch: ProposedPatch, *, apply_fix: bool, trace_id: str
    ) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="steward-proof-") as tmp:
            work = Path(tmp) / "repo"
            shutil.copytree(
                self._repo_path, work, ignore=shutil.ignore_patterns(".git", "__pycache__")
            )
            if apply_fix:
                self._apply(work, patch)
            self._write_proof(work, patch)
            spec = SandboxSpec(
                image=self._image,
                command=self._test_command.format(
                    proof_name=Path(patch.proof_test_path).name,
                    proof=patch.proof_test_path,
                ),
                repo_path=work,
                timeout_s=self._timeout_s,
            )
            return self._runner.run_tests(spec, trace_id=trace_id)

    @staticmethod
    def _apply(work: Path, patch: ProposedPatch) -> None:
        touched = patched_paths(patch.diff)
        current = {
            p: (work / p).read_text(encoding="utf-8") for p in touched if (work / p).exists()
        }
        for path, content in apply_patch(current, patch.diff).items():
            target = work / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    @staticmethod
    def _write_proof(work: Path, patch: ProposedPatch) -> None:
        target = work / patch.proof_test_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(patch.proof_test, encoding="utf-8")
