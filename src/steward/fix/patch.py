"""A small, pure unified-diff applier — the testable core of patch assembly.

A model proposes a fix as a unified diff; before that diff is ever trusted it
must **apply cleanly** to the real files. This module does exactly that, in
memory and with no side effects, so it is fully unit-testable: given the current
file contents and a diff, it returns the patched contents or raises
:class:`PatchDoesNotApply` when the diff's context does not match (CLAUDE.md §1
— a patch that doesn't apply is not a fix).

The supported subset is standard ``git diff`` / ``diff -u`` output: per-file
``---``/``+++`` headers, ``@@`` hunks, and ` `/`-`/`+` body lines, including new
files via ``--- /dev/null``. It is deliberately strict: anything it cannot apply
with confidence is rejected rather than guessed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(ValueError):
    """The diff is malformed and cannot be parsed."""


class PatchDoesNotApply(PatchError):
    """The diff parsed, but its context does not match the target file."""


@dataclass(slots=True)
class _Hunk:
    old_start: int
    lines: list[tuple[str, str]] = field(default_factory=list)  # (sign, text)


@dataclass(slots=True)
class _FilePatch:
    path: str
    is_new_file: bool
    hunks: list[_Hunk] = field(default_factory=list)


def _strip_prefix(path: str) -> str:
    """Drop a leading ``a/`` or ``b/`` from a diff header path."""
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _parse(diff: str) -> list[_FilePatch]:
    files: list[_FilePatch] = []
    current: _FilePatch | None = None
    hunk: _Hunk | None = None
    pending_old: str | None = None

    for raw in diff.splitlines():
        if raw.startswith("--- "):
            pending_old = raw[4:].strip()
            hunk = None
            continue
        if raw.startswith("+++ "):
            new_path = raw[4:].strip()
            path = _strip_prefix(new_path)
            current = _FilePatch(path=path, is_new_file=pending_old == "/dev/null")
            files.append(current)
            hunk = None
            continue
        if raw.startswith("@@"):
            m = _HUNK_RE.match(raw)
            if m is None:
                raise PatchError(f"malformed hunk header: {raw!r}")
            if current is None:
                raise PatchError("hunk appeared before any file header")
            hunk = _Hunk(old_start=int(m.group(1)))
            current.hunks.append(hunk)
            continue
        if hunk is None:
            # Ignore diff cruft between files (e.g. 'diff --git', 'index ...').
            continue
        if raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        sign = raw[0] if raw else " "
        if sign not in {" ", "+", "-"}:
            raise PatchError(f"unexpected diff line: {raw!r}")
        hunk.lines.append((sign, raw[1:]))

    if not files:
        raise PatchError("no file sections found in diff")
    return files


def _apply_file(original: str, fp: _FilePatch) -> str:
    if fp.is_new_file:
        added = [text for sign, text in (line for h in fp.hunks for line in h.lines) if sign == "+"]
        return "\n".join(added) + "\n"

    has_trailing_newline = original.endswith("\n")
    old_lines = original.split("\n")
    if has_trailing_newline:
        old_lines = old_lines[:-1]  # drop the empty element from the trailing "\n"

    out: list[str] = []
    pos = 0
    for hunk in sorted(fp.hunks, key=lambda h: h.old_start):
        start = hunk.old_start - 1
        if start < pos:
            raise PatchDoesNotApply(f"overlapping hunks in {fp.path}")
        out.extend(old_lines[pos:start])
        old_block = [text for sign, text in hunk.lines if sign in {" ", "-"}]
        actual = old_lines[start : start + len(old_block)]
        if actual != old_block:
            raise PatchDoesNotApply(f"context mismatch in {fp.path} at line {hunk.old_start}")
        new_block = [text for sign, text in hunk.lines if sign in {" ", "+"}]
        out.extend(new_block)
        pos = start + len(old_block)
    out.extend(old_lines[pos:])

    result = "\n".join(out)
    return result + "\n" if has_trailing_newline else result


def apply_patch(files: Mapping[str, str], diff: str) -> dict[str, str]:
    """Apply unified-``diff`` to ``files`` and return the full patched mapping.

    ``files`` maps repo-relative paths to their current contents. The return
    value is a copy with every patched file updated (and any new files added).
    Raises :class:`PatchError` if the diff is malformed and
    :class:`PatchDoesNotApply` if a hunk's context does not match — Steward never
    applies a patch it cannot place exactly.
    """
    parsed = _parse(diff)
    result = dict(files)
    for fp in parsed:
        if fp.is_new_file:
            if fp.path in result:
                raise PatchDoesNotApply(f"diff creates {fp.path} but it already exists")
            result[fp.path] = _apply_file("", fp)
            continue
        if fp.path not in result:
            raise PatchDoesNotApply(f"diff targets unknown file {fp.path}")
        result[fp.path] = _apply_file(result[fp.path], fp)
    return result


def patched_paths(diff: str) -> list[str]:
    """Return the repo-relative paths a ``diff`` touches (for scoping a copy)."""
    return [fp.path for fp in _parse(diff)]
