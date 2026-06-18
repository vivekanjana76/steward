"""The multi-agent reviewer council (issue #55).

A grounded, multi-agent gate that sits between VERIFY and the draft PR: a panel
of specialist reviewer agents (correctness, security, test quality) each judge a
proposed fix along one axis, and a supervisor aggregates their findings into one
go/no-go :class:`~steward.review.models.CouncilReview` (worst verdict wins).

Build an LLM-backed council with :func:`~steward.review.council.build_llm_council`
or the keyless deterministic one with
:func:`~steward.review.offline.build_offline_council`.
"""

from __future__ import annotations

from steward.review.council import (
    LLMReviewer,
    PatchReviewer,
    ReviewCouncil,
    Reviewer,
    build_llm_council,
)
from steward.review.models import (
    CouncilReview,
    ReviewContext,
    ReviewDimension,
    ReviewFinding,
    ReviewVerdict,
)
from steward.review.offline import build_offline_council

__all__ = [
    "CouncilReview",
    "LLMReviewer",
    "PatchReviewer",
    "ReviewContext",
    "ReviewCouncil",
    "ReviewDimension",
    "ReviewFinding",
    "ReviewVerdict",
    "Reviewer",
    "build_llm_council",
    "build_offline_council",
]
