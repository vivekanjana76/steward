"""Sanitization for untrusted issue/comment text.

Issue titles, bodies, and comments are **hostile input** (CLAUDE.md §5/§12):
they may carry prompt-injection aimed at the triage/repro/fix models, or hidden
Unicode used to smuggle instructions past a human reviewer. This module does two
separable things:

* :func:`sanitize_text` — normalize and strip dangerous/invisible characters,
  producing text that is safe to store and display. It never interprets the
  content; it only removes characters that have no legitimate place in an issue.
* :func:`detect_injection` — flag *signals* that the text is trying to subvert
  an LLM (e.g. "ignore previous instructions"). It does not modify the text;
  callers decide what to do with the signals (e.g. lower confidence, route to
  ``needs-info``, or wrap the text before sending it to a model).

Detection is deliberately conservative heuristics, not a guarantee. The grounded
rule still holds downstream: a signal is evidence to act cautiously, never proof.
"""

from __future__ import annotations

import re
import unicodedata

# Control characters (C0/C1) carry no meaning in issue text and can hide or
# reorder content; we keep only newline and tab from the C0 range.
_DISALLOWED_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Zero-width, bidirectional-override, word-joiner, isolate, and BOM code points.
# These are invisible and have been used to smuggle instructions past a human
# reviewer. Built from codepoint ranges so the source carries no invisible glyphs.
_INVISIBLE_RANGES: tuple[tuple[int, int], ...] = (
    (0x200B, 0x200F),  # zero-width space/non-joiner/joiner + LTR/RTL marks
    (0x202A, 0x202E),  # bidi embeddings and overrides
    (0x2060, 0x2064),  # word joiner + invisible math operators
    (0x2066, 0x2069),  # bidi isolates
    (0xFEFF, 0xFEFF),  # zero-width no-break space / BOM
)
_INVISIBLE = re.compile("[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _INVISIBLE_RANGES) + "]")


def sanitize_text(raw: str | None) -> str:
    """Return ``raw`` normalized and stripped of dangerous/invisible characters.

    Applies NFKC normalization, removes disallowed control characters and
    invisible/bidi code points, normalizes line endings, and trims surrounding
    whitespace. ``None`` becomes an empty string. The result is plain, visible
    text safe to store, display, and (after wrapping) hand to a model.
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _INVISIBLE.sub("", text)
    text = _DISALLOWED_CONTROL.sub("", text)
    return text.strip()


# Heuristic injection signatures, mapped to a canonical signal name. Patterns
# run case-insensitively over already-sanitized text.
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction-override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,30}\b"
            r"(previous|prior|above|earlier|all)\b.{0,30}"
            r"(instruction|instructions|prompt|prompts|context|rules?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "role-injection",
        re.compile(
            r"(^|\n)\s*(system|assistant|developer)\s*:"  # fake chat turns
            r"|</?(system|assistant|tool|tool_call)\b",  # fake role/tool tags
            re.IGNORECASE,
        ),
    ),
    (
        "persona-override",
        re.compile(r"\byou\s+are\s+now\b|\bact\s+as\b|\bpretend\s+to\s+be\b", re.IGNORECASE),
    ),
    (
        "prompt-exfiltration",
        re.compile(
            r"\b(reveal|print|repeat|show|disclose)\b.{0,30}\b(system\s+)?prompt\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
)


def detect_injection(text: str) -> tuple[str, ...]:
    """Return the sorted, de-duplicated injection signals found in ``text``.

    Signals are heuristic flags (e.g. ``"instruction-override"``) — evidence to
    treat the text cautiously, not proof of intent. An empty tuple means no
    known pattern matched. Best run on :func:`sanitize_text` output.
    """
    found = {name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)}
    return tuple(sorted(found))
