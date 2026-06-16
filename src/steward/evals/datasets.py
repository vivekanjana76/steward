"""Typed loaders for the versioned, labeled eval datasets (CLAUDE.md §10).

The datasets live as JSONL under ``evals/`` and are committed so they grow
case-by-case (every regression becomes a permanent case). These loaders validate
each line into a frozen Pydantic model, so a malformed dataset fails loudly
rather than silently skewing a metric.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict

# Datasets are addressed relative to the repo root by default.
EVALS_DIR = Path("evals")
TRIAGE_DIR = EVALS_DIR / "triage"
CLASSIFICATION_CASES = TRIAGE_DIR / "classification_cases.jsonl"
DUPLICATE_CASES = TRIAGE_DIR / "duplicate_cases.jsonl"


class ClassificationCase(BaseModel):
    """One labeled triage-classification case.

    Exactly one of ``expected_category`` or ``expected_needs_info`` is the label;
    ``expected_injection_signal``, when present, must be surfaced at ingestion.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    body: str = ""
    expected_category: str | None = None
    expected_needs_info: bool = False
    expected_injection_signal: str | None = None
    notes: str | None = None


class DuplicateCase(BaseModel):
    """One issue in the duplicate-detection corpus; ``duplicate_of`` is the label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    number: int
    title: str
    body: str = ""
    duplicate_of: int | None = None
    notes: str | None = None


def _read_jsonl(path: Path) -> Iterator[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_classification_cases(path: Path = CLASSIFICATION_CASES) -> list[ClassificationCase]:
    """Load and validate the classification dataset."""
    return [ClassificationCase.model_validate(row) for row in _read_jsonl(path)]


def load_duplicate_cases(path: Path = DUPLICATE_CASES) -> list[DuplicateCase]:
    """Load and validate the duplicate-detection corpus."""
    return [DuplicateCase.model_validate(row) for row in _read_jsonl(path)]
