"""Unit tests for model-backed patch generation (issue #15).

A real :class:`ModelClient` runs against an in-memory Anthropic stub, so the
actual forced-tool-use path is exercised with no network. The focus: the
generator uses the Opus *patch* role, and it never returns a diff that does not
apply cleanly — a hallucinated patch is rejected here, not downstream.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from steward.fix.generate import FixGenerationError, PatchGenerator
from steward.graph.state import GraphState
from steward.llm.client import ModelClient, ModelRole, model_for
from steward.triage.models import IssueState, NormalizedIssue

_CALC = "def add(a, b):\n    return a - b\n"

_GOOD_DIFF = (
    "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n-    return a - b\n+    return a + b\n"
)
_PROOF = (
    "import unittest\nfrom calc import add\n\n"
    "class T(unittest.TestCase):\n"
    "    def test_add(self):\n"
    "        self.assertEqual(add(1, 1), 2)\n"
)


def _tool_response(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        model="stub",
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=50, output_tokens=120),
        content=[SimpleNamespace(type="tool_use", name="format_response", input=payload)],
    )


class _StubMessages:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _StubAnthropic:
    def __init__(self, response: Any) -> None:
        self.messages = _StubMessages(response)


def _state() -> GraphState:
    now = datetime(2026, 6, 15, tzinfo=UTC)
    issue = NormalizedIssue(
        number=12,
        title="add() subtracts",
        body="add(1, 1) returns 0",
        state=IssueState.OPEN,
        created_at=now,
        updated_at=now,
    )
    return GraphState(issue=issue, trace_id="t", hypothesis="wrong operator in add()")


def _generator(payload: dict[str, Any]) -> tuple[PatchGenerator, _StubAnthropic]:
    stub = _StubAnthropic(_tool_response(payload))
    client = ModelClient(client=stub)
    return PatchGenerator(client, repo_files={"calc.py": _CALC}), stub


def test_returns_patch_and_uses_opus_patch_role() -> None:
    gen, stub = _generator(
        {"diff": _GOOD_DIFF, "proof_test": _PROOF, "proof_test_path": "test_steward_proof.py"}
    )
    patch = gen.propose(_state())
    assert patch.diff == _GOOD_DIFF
    assert patch.proof_test_path == "test_steward_proof.py"
    # Routed through the central client at the Opus patch role, via forced tool use.
    call = stub.messages.calls[0]
    assert call["model"] == model_for(ModelRole.PATCH)
    assert "tools" in call


def test_rejects_a_diff_that_does_not_apply() -> None:
    bad = _GOOD_DIFF.replace("def add(a, b):", "def mul(a, b):")
    gen, _ = _generator({"diff": bad, "proof_test": _PROOF})
    with pytest.raises(FixGenerationError, match="does not apply"):
        gen.propose(_state())


def test_rejects_a_malformed_diff() -> None:
    gen, _ = _generator({"diff": "totally not a diff", "proof_test": _PROOF})
    with pytest.raises(FixGenerationError, match="malformed"):
        gen.propose(_state())
