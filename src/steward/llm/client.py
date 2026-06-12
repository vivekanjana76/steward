"""The single entry point for Anthropic model access.

Every model call in Steward MUST go through this module so that:

* the mapping from a logical *role* to a concrete model lives in one place and
  can be changed without touching call sites (CLAUDE.md §4), and
* requests and responses are typed (Pydantic), so node boundaries stay
  contract-checked.

Two surfaces are exposed:

* :meth:`ModelClient.complete` — a plain text completion.
* :meth:`ModelClient.structured` — a completion whose result is validated into a
  caller-supplied Pydantic model, implemented with Anthropic forced tool use so
  the model returns schema-shaped JSON rather than free text.

Network access is confined to :class:`ModelClient`; everything else in this
module is pure and import-safe (no SDK construction, no env reads at import).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field, ValidationError

from steward.config import Settings, get_settings


class _AnthropicLike(Protocol):
    """The slice of the Anthropic SDK surface that :class:`ModelClient` uses.

    Depending on this structural type (rather than the concrete ``Anthropic``
    class) keeps the SDK an implementation detail and lets tests inject a stub
    with no network access.
    """

    messages: Any


class ModelRole(StrEnum):
    """The job a model call performs, used to pick a concrete model.

    Routine work defaults to Sonnet; high-stakes reasoning (planning, patch
    generation, and verification) uses Opus (CLAUDE.md §4).
    """

    ROUTINE = "routine"
    PLANNER = "planner"
    PATCH = "patch"
    VERIFIER = "verifier"


# Single source of truth for model selection. Changing a model is a one-line
# edit here — never hardcode a model id at a call site.
_ROLE_TO_MODEL: dict[ModelRole, str] = {
    ModelRole.ROUTINE: "claude-sonnet-4-6",
    ModelRole.PLANNER: "claude-opus-4-8",
    ModelRole.PATCH: "claude-opus-4-8",
    ModelRole.VERIFIER: "claude-opus-4-8",
}


def model_for(role: ModelRole) -> str:
    """Return the concrete Anthropic model id for a logical ``role``."""
    return _ROLE_TO_MODEL[role]


class Message(BaseModel):
    """A single conversation turn handed to the model."""

    role: Literal["user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    """A model request expressed in role terms, not model-id terms.

    The concrete model is resolved from :attr:`role` at call time, so callers
    never name a model. ``temperature`` defaults to ``0.0`` because Steward
    favours determinism for triage/verification reasoning.
    """

    role: ModelRole
    messages: list[Message] = Field(min_length=1)
    system: str | None = None
    max_tokens: int = Field(default=1024, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)


class TokenUsage(BaseModel):
    """Token counts for a single call, used for cost/observability (CLAUDE.md §11)."""

    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    """A normalized model response."""

    model: str
    text: str
    usage: TokenUsage
    stop_reason: str | None = None


T = TypeVar("T", bound=BaseModel)

_STRUCTURED_TOOL_NAME = "format_response"


class ModelClientError(RuntimeError):
    """Raised when the model client cannot produce a usable response."""


class ModelClient:
    """Thin, typed wrapper around the Anthropic SDK.

    Construct via :func:`get_model_client` in application code; the explicit
    ``client`` argument exists so tests can inject a stub and never touch the
    network.
    """

    def __init__(self, *, client: _AnthropicLike) -> None:
        self._client = client

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Run a text completion for ``request`` and return the normalized result."""
        model = model_for(request.role)
        raw = self._client.messages.create(
            model=model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            messages=[m.model_dump() for m in request.messages],
            **self._system_kwargs(request),
        )
        text = self._first_text_block(raw)
        return LLMResponse(
            model=getattr(raw, "model", model),
            text=text,
            usage=self._usage(raw),
            stop_reason=getattr(raw, "stop_reason", None),
        )

    def structured(self, request: LLMRequest, schema: type[T]) -> T:
        """Run a completion whose JSON result is validated into ``schema``.

        Implemented with Anthropic forced tool use: ``schema`` becomes the input
        schema of a single tool the model is required to call, so the returned
        arguments are validated directly against ``schema``.
        """
        model = model_for(request.role)
        tool = {
            "name": _STRUCTURED_TOOL_NAME,
            "description": f"Return a well-formed {schema.__name__} object.",
            "input_schema": schema.model_json_schema(),
        }
        raw = self._client.messages.create(
            model=model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            messages=[m.model_dump() for m in request.messages],
            tools=[tool],
            tool_choice={"type": "tool", "name": _STRUCTURED_TOOL_NAME},
            **self._system_kwargs(request),
        )
        payload = self._first_tool_input(raw)
        try:
            return schema.model_validate(payload)
        except ValidationError as exc:  # pragma: no cover - exercised via tests
            raise ModelClientError(
                f"model returned a payload that did not match {schema.__name__}"
            ) from exc

    @staticmethod
    def _system_kwargs(request: LLMRequest) -> dict[str, Any]:
        return {"system": request.system} if request.system is not None else {}

    @staticmethod
    def _usage(raw: Any) -> TokenUsage:
        usage = getattr(raw, "usage", None)
        if usage is None:
            return TokenUsage()
        return TokenUsage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )

    @staticmethod
    def _first_text_block(raw: Any) -> str:
        for block in getattr(raw, "content", []) or []:
            if getattr(block, "type", None) == "text":
                return getattr(block, "text", "")
        raise ModelClientError("model response contained no text block")

    @staticmethod
    def _first_tool_input(raw: Any) -> Any:
        for block in getattr(raw, "content", []) or []:
            if getattr(block, "type", None) == "tool_use":
                return getattr(block, "input", {})
        raise ModelClientError("model response contained no tool_use block")


def build_model_client(settings: Settings) -> ModelClient:
    """Construct a :class:`ModelClient` from ``settings``.

    Raises :class:`ModelClientError` if no API key is configured, so the failure
    is explicit rather than surfacing deep inside the SDK on first call.
    """
    if not settings.anthropic_api_key:
        raise ModelClientError(
            "ANTHROPIC_API_KEY is not set; configure it in the environment or .env"
        )
    from anthropic import Anthropic

    return ModelClient(client=Anthropic(api_key=settings.anthropic_api_key))


def get_model_client() -> ModelClient:
    """Return a :class:`ModelClient` built from the process-wide settings."""
    return build_model_client(get_settings())
