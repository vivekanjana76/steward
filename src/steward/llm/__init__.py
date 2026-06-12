"""Model access layer.

All Anthropic model calls go through :mod:`steward.llm.client` so that the
model used for each role can be swapped in exactly one place (CLAUDE.md §4).
"""

from steward.llm.client import (
    LLMRequest,
    LLMResponse,
    Message,
    ModelClient,
    ModelClientError,
    ModelRole,
    TokenUsage,
    build_model_client,
    get_model_client,
    model_for,
)

__all__ = [
    "LLMRequest",
    "LLMResponse",
    "Message",
    "ModelClient",
    "ModelClientError",
    "ModelRole",
    "TokenUsage",
    "build_model_client",
    "get_model_client",
    "model_for",
]
