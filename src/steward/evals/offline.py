"""Deterministic, keyless backends so the eval pipeline runs in CI.

The eval suite measures Steward's *real* classifier and duplicate detector when
``ANTHROPIC_API_KEY`` / ``VOYAGE_API_KEY`` are configured. Without keys (CI, and
this project until the end), it falls back to these offline reference backends so
the harness, metrics, report, and baseline **gate** are still exercised
end-to-end and deterministically. Reports clearly record which backend produced
the numbers, so an offline run is never mistaken for the live model's score.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

from steward.triage.classify import IssueCategory, TriageDecision
from steward.triage.models import NormalizedIssue

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "is",
        "are",
        "it",
        "this",
        "that",
        "with",
        "i",
        "we",
        "you",
        "my",
        "our",
        "be",
        "can",
        "do",
        "does",
        "not",
        "no",
        "nothing",
        "get",
        "got",
        "when",
        "where",
        "how",
        "what",
        "why",
        "which",
        "as",
        "at",
        "by",
        "so",
        "just",
        "please",
        "would",
        "like",
        "add",
        "more",
        "less",
        "than",
        "from",
        "into",
        "out",
        "up",
    ]
)

_BUG_WORDS = frozenset(
    [
        "crash",
        "crashes",
        "crashed",
        "segfault",
        "error",
        "errors",
        "exception",
        "traceback",
        "broken",
        "break",
        "breaks",
        "fails",
        "failing",
        "failed",
        "bug",
        "regression",
        "unresponsive",
        "typeerror",
        "exits",
        "exit",
        "incorrect",
        "wrong",
        "off",
        "doesn't",
        "does't",
        "cannot",
        "can't",
        "unable",
    ]
)
_FEATURE_WORDS = frozenset(
    [
        "add",
        "allow",
        "support",
        "feature",
        "enhancement",
        "export",
        "import",
        "theme",
        "option",
        "ability",
        "nice",
        "button",
        "able",
        "provide",
        "enable",
    ]
)
_QUESTION_WORDS = frozenset(
    ["where", "how", "why", "what", "which", "is", "question", "understand", "setup"]
)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


class OfflineClassifier:
    """A keyword-heuristic stand-in for :class:`IssueClassifier` (offline runs).

    It is intentionally simple and general — not tuned to the eval set — so the
    baseline it produces is a real, if modest, measurement of a deterministic
    reference, not a faked perfect score.
    """

    def classify(self, issue: NormalizedIssue) -> TriageDecision:
        informative = f"{issue.title} {issue.body}".strip()
        # Too little to classify confidently -> needs-info, never a guess.
        if len(informative) < 12 or (not issue.body.strip() and len(issue.title.split()) <= 2):
            return TriageDecision(
                category=IssueCategory.QUESTION,
                confidence=0.3,
                rationale="insufficient information to classify",
                needs_info=True,
                injection_signals=issue.injection_signals,
            )
        toks = set(_tokens(informative))
        scores = {
            IssueCategory.BUG: len(toks & _BUG_WORDS),
            IssueCategory.FEATURE: len(toks & _FEATURE_WORDS),
            IssueCategory.QUESTION: len(toks & _QUESTION_WORDS),
        }
        best = max(scores, key=lambda c: scores[c])
        if scores[best] == 0:
            best = IssueCategory.QUESTION  # default for unclassifiable prose
        return TriageDecision(
            category=best,
            confidence=0.8,
            rationale=f"keyword heuristic matched {scores[best]} {best.value} term(s)",
            needs_info=False,
            injection_signals=issue.injection_signals,
        )


class HashingTfEmbedder:
    """A deterministic term-frequency hashing embedder (offline dedup runs).

    Tokens are hashed into a fixed-dimension vector, L2-normalized, so cosine
    similarity reflects shared vocabulary. No network, fully reproducible.
    """

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    @property
    def model(self) -> str:
        return f"offline-tf-hash-{self._dim}"

    def embed(
        self, texts: Sequence[str], *, input_type: str = "document"
    ) -> list[tuple[float, ...]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> tuple[float, ...]:
        vec = [0.0] * self._dim
        for token in _tokens(text):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            vec[int(digest, 16) % self._dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return tuple(vec)
        return tuple(x / norm for x in vec)
