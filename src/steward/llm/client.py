"""The single entry point for Anthropic model selection.

Every model call in Steward MUST resolve its model through this module so the
mapping from a logical *role* to a concrete model lives in one place and can be
changed without touching call sites (CLAUDE.md §4).

This is the scaffold: it defines the role -> model mapping and the resolution
helper. The actual request/response client (typed wrappers, structured output,
retries, token/cost capture) is implemented in issue #2.
"""

from __future__ import annotations

from enum import StrEnum


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
