"""Fix generation: a minimal patch plus a proof test that proves it (#15).

* :func:`apply_patch` — the pure, testable unified-diff applier that rejects any
  diff which does not apply cleanly.
* :class:`PatchGenerator` — model-backed generation of a :class:`ProposedPatch`
  (the graph's ``Patcher`` seam), validated to apply before it is returned.
* :class:`SandboxProofTester` — proves the patch in the sandbox by a genuine
  fail-before / pass-after run (the graph's ``Tester`` seam).
"""

from __future__ import annotations

from steward.fix.generate import FixGenerationError, PatchGenerator
from steward.fix.patch import (
    PatchDoesNotApply,
    PatchError,
    apply_patch,
    patched_paths,
)
from steward.fix.prooftest import DEFAULT_PROOF_COMMAND, SandboxProofTester

__all__ = [
    "DEFAULT_PROOF_COMMAND",
    "FixGenerationError",
    "PatchDoesNotApply",
    "PatchError",
    "PatchGenerator",
    "SandboxProofTester",
    "apply_patch",
    "patched_paths",
]
