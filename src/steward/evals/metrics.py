"""Pure metric functions for the eval suite (CLAUDE.md §10).

Evaluation is first-class product code: these functions turn (prediction, label)
pairs into the numbers the scorecard publishes — classification accuracy/F1 and
duplicate-detection precision/recall. They are pure and deterministic, so the
numbers are reproducible and the functions are trivially unit-tested.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field


class ClassMetric(BaseModel):
    """Precision/recall/F1 and support for a single class."""

    model_config = {"frozen": True}

    precision: float
    recall: float
    f1: float
    support: int


class ClassificationMetrics(BaseModel):
    """Multi-class classification metrics over a labeled set."""

    model_config = {"frozen": True}

    accuracy: float
    macro_f1: float
    per_class: dict[str, ClassMetric] = Field(default_factory=dict)
    n: int


class BinaryMetrics(BaseModel):
    """Precision/recall/F1 for a binary decision (e.g. is-a-duplicate)."""

    model_config = {"frozen": True}

    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    tn: int


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def classification_metrics(
    pairs: Sequence[tuple[str, str]], labels: Sequence[str]
) -> ClassificationMetrics:
    """Compute accuracy + per-class and macro F1 from (predicted, expected) pairs.

    ``labels`` is the full label set, so a class with no predictions still gets a
    (zero) row — macro-F1 averages over all of them, not just the seen ones.
    """
    correct = sum(1 for pred, exp in pairs if pred == exp)
    n = len(pairs)
    per_class: dict[str, ClassMetric] = {}
    for label in labels:
        tp = sum(1 for pred, exp in pairs if pred == label and exp == label)
        fp = sum(1 for pred, exp in pairs if pred == label and exp != label)
        fn = sum(1 for pred, exp in pairs if pred != label and exp == label)
        support = sum(1 for _, exp in pairs if exp == label)
        precision, recall, f1 = _prf(tp, fp, fn)
        per_class[label] = ClassMetric(precision=precision, recall=recall, f1=f1, support=support)
    # Macro-F1 averages over the classes actually present in the labels (support
    # > 0): a class the model failed to predict still counts (F1 = 0), but a
    # class absent from the data does not dilute the score.
    present = [m.f1 for m in per_class.values() if m.support > 0]
    macro_f1 = sum(present) / len(present) if present else 0.0
    accuracy = correct / n if n else 0.0
    return ClassificationMetrics(accuracy=accuracy, macro_f1=macro_f1, per_class=per_class, n=n)


def binary_metrics(decisions: Sequence[tuple[bool, bool]]) -> BinaryMetrics:
    """Compute precision/recall/F1 from (predicted_positive, actual_positive) pairs."""
    tp = sum(1 for pred, act in decisions if pred and act)
    fp = sum(1 for pred, act in decisions if pred and not act)
    fn = sum(1 for pred, act in decisions if not pred and act)
    tn = sum(1 for pred, act in decisions if not pred and not act)
    precision, recall, f1 = _prf(tp, fp, fn)
    return BinaryMetrics(precision=precision, recall=recall, f1=f1, tp=tp, fp=fp, fn=fn, tn=tn)
