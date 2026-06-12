"""Unit tests for the central Anthropic model client.

The Anthropic SDK is replaced by an in-memory stub so these tests are fast,
deterministic, and never touch the network (CLAUDE.md §9).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from steward.config import Settings
from steward.llm.client import (
    LLMRequest,
    Message,
    ModelClient,
    ModelClientError,
    ModelRole,
    build_model_client,
    model_for,
)


def _text_response(text: str = "hello", *, model: str = "stub-model") -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        content=[SimpleNamespace(type="text", text=text)],
    )


def _tool_response(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        model="stub-model",
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=3, output_tokens=5),
        content=[SimpleNamespace(type="tool_use", name="format_response", input=payload)],
    )


class _StubMessages:
    """Records the kwargs of the last `create` call and returns a canned reply."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _StubAnthropic:
    def __init__(self, response: Any) -> None:
        self.messages = _StubMessages(response)


def _client(response: Any) -> tuple[ModelClient, _StubAnthropic]:
    stub = _StubAnthropic(response)
    return ModelClient(client=stub), stub


def test_role_resolution_matches_spec() -> None:
    assert model_for(ModelRole.ROUTINE) == "claude-sonnet-4-6"
    for role in (ModelRole.PLANNER, ModelRole.PATCH, ModelRole.VERIFIER):
        assert model_for(role) == "claude-opus-4-8"


def test_complete_uses_role_model_and_normalizes_response() -> None:
    client, stub = _client(_text_response("hi there", model="claude-opus-4-8"))
    req = LLMRequest(role=ModelRole.PLANNER, messages=[Message(role="user", content="ping")])

    resp = client.complete(req)

    assert stub.messages.calls[0]["model"] == "claude-opus-4-8"
    assert resp.text == "hi there"
    assert resp.model == "claude-opus-4-8"
    assert resp.usage.input_tokens == 11
    assert resp.usage.output_tokens == 7
    assert resp.stop_reason == "end_turn"


def test_complete_omits_system_when_unset_and_passes_it_when_set() -> None:
    client, stub = _client(_text_response())
    client.complete(
        LLMRequest(role=ModelRole.ROUTINE, messages=[Message(role="user", content="x")])
    )
    assert "system" not in stub.messages.calls[0]

    client2, stub2 = _client(_text_response())
    client2.complete(
        LLMRequest(
            role=ModelRole.ROUTINE,
            messages=[Message(role="user", content="x")],
            system="be terse",
        )
    )
    assert stub2.messages.calls[0]["system"] == "be terse"


def test_complete_raises_without_text_block() -> None:
    client, _ = _client(_tool_response({"a": 1}))
    with pytest.raises(ModelClientError):
        client.complete(
            LLMRequest(role=ModelRole.ROUTINE, messages=[Message(role="user", content="x")])
        )


def test_structured_forces_tool_use_and_validates_payload() -> None:
    from pydantic import BaseModel

    class Verdict(BaseModel):
        category: str
        confidence: float

    client, stub = _client(_tool_response({"category": "bug", "confidence": 0.9}))
    result = client.structured(
        LLMRequest(role=ModelRole.ROUTINE, messages=[Message(role="user", content="classify")]),
        Verdict,
    )

    call = stub.messages.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "format_response"}
    assert call["tools"][0]["name"] == "format_response"
    assert call["tools"][0]["input_schema"] == Verdict.model_json_schema()
    assert isinstance(result, Verdict)
    assert result.category == "bug"
    assert result.confidence == 0.9


def test_structured_raises_on_schema_mismatch() -> None:
    from pydantic import BaseModel

    class Verdict(BaseModel):
        category: str
        confidence: float

    client, _ = _client(_tool_response({"category": "bug"}))  # missing confidence
    with pytest.raises(ModelClientError):
        client.structured(
            LLMRequest(role=ModelRole.ROUTINE, messages=[Message(role="user", content="x")]),
            Verdict,
        )


def test_request_requires_at_least_one_message() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LLMRequest(role=ModelRole.ROUTINE, messages=[])


def test_build_model_client_requires_api_key() -> None:
    # model_construct bypasses env/.env so the test never depends on ambient keys.
    with pytest.raises(ModelClientError):
        build_model_client(Settings.model_construct(anthropic_api_key=None))


def test_build_model_client_constructs_with_key() -> None:
    client = build_model_client(Settings.model_construct(anthropic_api_key="sk-test-not-real"))
    assert isinstance(client, ModelClient)
