"""Run the eval suite, write a report, and gate against the baseline.

``python -m steward.evals`` (or ``just eval``): score triage classification and
duplicate detection, write ``evals/report.json``, and exit non-zero if any core
metric dropped below ``evals/baseline.json`` (CLAUDE.md §10).

Backends are chosen by configuration: the **live** model / embeddings when their
keys are set, the deterministic **offline** reference backends otherwise. The
report records which was used, so an offline run is never mistaken for the live
score. ``--write-baseline`` regenerates the baseline (do this only in a reviewed
PR — never to make a failing run pass).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from steward.config import Settings, get_settings
from steward.evals.datasets import load_classification_cases, load_duplicate_cases
from steward.evals.offline import HashingTfEmbedder, OfflineClassifier
from steward.evals.report import (
    BASELINE_PATH,
    REPORT_PATH,
    EvalReport,
    check_regressions,
    load_baseline,
)
from steward.evals.triage import Classify, run_classification_eval, run_dedup_eval
from steward.triage.dedup import (
    DEFAULT_SIMILARITY_THRESHOLD,
    DuplicateDetector,
    Embedder,
    InMemoryVectorStore,
)

_OFFLINE_DEDUP_THRESHOLD = 0.25
_SUBSET = "triage-v1"


def _classifier(settings: Settings) -> tuple[Classify, str]:
    if settings.anthropic_api_key:
        from steward.llm.client import build_model_client
        from steward.triage.classify import IssueClassifier

        return IssueClassifier(build_model_client(settings)).classify, "live"
    return OfflineClassifier().classify, "offline"


def _embedder(settings: Settings) -> tuple[Embedder, float, str]:
    if settings.voyage_api_key:
        try:
            from steward.triage.dedup import build_embedder

            return build_embedder(settings), DEFAULT_SIMILARITY_THRESHOLD, "live"
        except ImportError:
            pass
    return HashingTfEmbedder(), _OFFLINE_DEDUP_THRESHOLD, "offline"


def build_report(settings: Settings) -> EvalReport:
    """Run every eval against the configured backends and assemble the report."""
    classify, clf_backend = _classifier(settings)
    embedder, threshold, emb_backend = _embedder(settings)

    classification = run_classification_eval(load_classification_cases(), classify)
    detector = DuplicateDetector(embedder, InMemoryVectorStore(), threshold=threshold)
    dedup = run_dedup_eval(load_duplicate_cases(), detector)

    metrics = {
        "triage_f1": classification.metrics.macro_f1,
        "triage_accuracy": classification.metrics.accuracy,
        "injection_recall": classification.injection_recall,
        "dedup_precision": dedup.precision,
        "dedup_recall": dedup.recall,
    }
    backend = "live" if clf_backend == "live" and emb_backend == "live" else "offline"
    details = {
        "classification": {
            "backend": clf_backend,
            "per_class": {k: v.model_dump() for k, v in classification.metrics.per_class.items()},
            "injection_cases": classification.injection_cases,
        },
        "dedup": {
            "backend": emb_backend,
            "embedding_model": embedder.model,
            "threshold": threshold,
            "counts": {"tp": dedup.tp, "fp": dedup.fp, "fn": dedup.fn, "tn": dedup.tn},
        },
    }
    return EvalReport.create(backend=backend, subset=_SUBSET, metrics=metrics, details=details)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Steward eval suite.")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write the run to evals/baseline.json (reviewed PRs only).",
    )
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    args = parser.parse_args(argv)

    report = build_report(get_settings())
    report.write(args.report)
    print(f"eval backend={report.backend} subset={report.subset}")
    for key, value in report.metrics.items():
        print(f"  {key}: {value:.4f}")

    if args.write_baseline:
        report.write(args.baseline)
        print(f"wrote baseline -> {args.baseline}")
        return 0

    regressions = check_regressions(report.metrics, load_baseline(args.baseline))
    if regressions:
        print("\nREGRESSION vs baseline:", file=sys.stderr)
        for reg in regressions:
            print(f"  {reg.describe()}", file=sys.stderr)
        return 1
    print("\nno regressions vs baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
