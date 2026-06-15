"""Unit tests for the pure unified-diff applier (issue #15).

The applier is the testable core of patch assembly: it applies cleanly or it
rejects. These tests pin both — successful application (single/multi-hunk, new
files, newline handling) and refusal on any mismatch or malformed input.
"""

from __future__ import annotations

import pytest

from steward.fix.patch import (
    PatchDoesNotApply,
    PatchError,
    apply_patch,
    patched_paths,
)

_CALC = "def add(a, b):\n    return a - b\n"

_FIX = """--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


def test_applies_a_single_hunk() -> None:
    out = apply_patch({"calc.py": _CALC}, _FIX)
    assert out["calc.py"] == "def add(a, b):\n    return a + b\n"


def test_patched_paths_lists_targets() -> None:
    assert patched_paths(_FIX) == ["calc.py"]


def test_creates_a_new_file_from_dev_null() -> None:
    diff = "--- /dev/null\n+++ b/test_new.py\n@@ -0,0 +1,2 @@\n+def test_x():\n+    assert True\n"
    out = apply_patch({"calc.py": _CALC}, diff)
    assert out["test_new.py"] == "def test_x():\n    assert True\n"
    assert out["calc.py"] == _CALC  # untouched


def test_applies_multiple_hunks() -> None:
    original = "\n".join(f"line{i}" for i in range(1, 9)) + "\n"
    diff = (
        "--- a/f.txt\n+++ b/f.txt\n"
        "@@ -1,2 +1,2 @@\n line1\n-line2\n+LINE2\n"
        "@@ -7,2 +7,2 @@\n line7\n-line8\n+LINE8\n"
    )
    out = apply_patch({"f.txt": original}, diff)
    assert "LINE2" in out["f.txt"]
    assert "LINE8" in out["f.txt"]
    assert "line4" in out["f.txt"]  # untouched middle preserved


def test_preserves_absence_of_trailing_newline() -> None:
    original = "a\nb"  # no trailing newline
    diff = "--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n a\n-b\n+B\n"
    assert apply_patch({"f": original}, diff)["f"] == "a\nB"


def test_rejects_context_mismatch() -> None:
    bad = _FIX.replace("def add(a, b):", "def subtract(a, b):")
    with pytest.raises(PatchDoesNotApply, match="context mismatch"):
        apply_patch({"calc.py": _CALC}, bad)


def test_rejects_unknown_target_file() -> None:
    with pytest.raises(PatchDoesNotApply, match="unknown file"):
        apply_patch({"other.py": _CALC}, _FIX)


def test_rejects_creating_an_existing_file() -> None:
    diff = "--- /dev/null\n+++ b/calc.py\n@@ -0,0 +1,1 @@\n+x = 1\n"
    with pytest.raises(PatchDoesNotApply, match="already exists"):
        apply_patch({"calc.py": _CALC}, diff)


def test_rejects_malformed_hunk_header() -> None:
    diff = "--- a/f\n+++ b/f\n@@ this is not a hunk @@\n x\n"
    with pytest.raises(PatchError, match="malformed hunk"):
        apply_patch({"f": "x\n"}, diff)


def test_rejects_empty_diff() -> None:
    with pytest.raises(PatchError, match="no file sections"):
        apply_patch({"f": "x\n"}, "not a diff at all\n")


def test_ignores_git_diff_cruft() -> None:
    diff = (
        "diff --git a/calc.py b/calc.py\n"
        "index 1234567..89abcde 100644\n"
        "--- a/calc.py\n+++ b/calc.py\n"
        "@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
    )
    out = apply_patch({"calc.py": _CALC}, diff)
    assert out["calc.py"] == "def add(a, b):\n    return a + b\n"
