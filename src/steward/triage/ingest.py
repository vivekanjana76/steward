"""Map raw GitHub issue payloads onto :class:`NormalizedIssue`.

This is the single boundary where untrusted, source-shaped data becomes a typed
Steward model. Every free-text field is sanitized here (CLAUDE.md §5), and
prompt-injection heuristics are run once over the combined text so the resulting
:class:`NormalizedIssue` carries its signals.

The adapter is tolerant of the well-known shape variations in GitHub payloads
(labels as strings or objects, a missing/ghost author, an absent body) but
relies on Pydantic to reject anything structurally invalid (e.g. a missing
``number`` or an unparseable timestamp), so bad input fails loudly at the edge
rather than silently downstream.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from steward.triage.models import IssueComment, NormalizedIssue
from steward.triage.sanitize import detect_injection, sanitize_text


def _author_login(node: Mapping[str, Any] | None) -> str | None:
    """Extract a ``login`` from a GitHub ``user`` object, tolerating ``None``."""
    if not node:
        return None
    login = node.get("login")
    return login if isinstance(login, str) else None


def _label_names(labels: Iterable[Any] | None) -> tuple[str, ...]:
    """Normalize GitHub labels (strings or ``{"name": ...}`` objects) to names."""
    if not labels:
        return ()
    names: list[str] = []
    for label in labels:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, Mapping):
            name = label.get("name")
            if isinstance(name, str):
                names.append(name)
    return tuple(names)


def _normalize_comment(raw: Mapping[str, Any]) -> IssueComment:
    return IssueComment(
        comment_id=raw["id"],
        author=_author_login(raw.get("user")),
        body=sanitize_text(raw.get("body")),
        created_at=raw["created_at"],
    )


def normalize_issue(
    issue: Mapping[str, Any],
    comments: Iterable[Mapping[str, Any]] | None = None,
) -> NormalizedIssue:
    """Map a GitHub issue payload (and optional comments) to a normalized model.

    ``issue`` is a GitHub REST issue object; ``comments`` is the optional list
    from the issue's comments endpoint. Title, body, and comment bodies are
    sanitized, and injection detection runs once across all of them. Raises
    :class:`KeyError` if a structurally required field (``number``, ``state``,
    ``created_at``, ``updated_at``) is absent, and
    :class:`pydantic.ValidationError` if a present value fails validation (e.g.
    an unparseable timestamp or an unknown state).
    """
    title = sanitize_text(issue.get("title"))
    body = sanitize_text(issue.get("body"))
    normalized_comments = tuple(_normalize_comment(c) for c in (comments or ()))

    haystack = "\n".join([title, body, *(c.body for c in normalized_comments)])
    signals = detect_injection(haystack)

    return NormalizedIssue(
        number=issue["number"],
        title=title,
        body=body,
        author=_author_login(issue.get("user")),
        state=issue["state"],
        labels=_label_names(issue.get("labels")),
        created_at=issue["created_at"],
        updated_at=issue["updated_at"],
        comments=normalized_comments,
        injection_signals=signals,
    )
