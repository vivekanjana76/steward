"""`just demo` — point Steward at the controlled demo repo, one dry-run cycle.

Runs the full pipeline against [`demo/`](../../demo/) — a small shop app we own,
seeded with realistic issues (a bug, its duplicate, and a needs-info report).
Everything is **dry-run**: no external calls, no world mutation. It works with
**no API keys and no Docker** by wiring deterministic offline seams, and the
"fix proven" evidence is real — the proof runs the demo's actual code before and
after the patch, in-process.

Narrative per issue:

* the **bug** (#1): triage → reproduce → patch → proof test fails-before /
  passes-after → VERIFY → the multi-agent review **council** approves → a draft
  PR is *proposed* (queued for human approval, audited as dry-run); nothing is
  opened on GitHub.
* the **duplicate** (#2): detected as a duplicate of #1; Steward would comment +
  label, not fix.
* the **needs-info** report (#3): too thin to act on; routed to needs-info.

Run: ``just demo`` (raw: ``uv run python -m steward.demo``).
"""

from __future__ import annotations

import json
import sys
from contextlib import suppress
from pathlib import Path

from pydantic import BaseModel

from steward.config import Settings
from steward.evals.offline import HashingTfEmbedder, OfflineClassifier, OfflineReproducer
from steward.fix.draft_pr import DraftPullRequestOpener, PullRequestRef, render_pr_body
from steward.fix.patch import apply_patch
from steward.graph import (
    GraphOutcome,
    GraphState,
    ProposedPatch,
    ReproOutcome,
    ReproVerdict,
    StewardDeps,
    build_graph,
    run_issue,
)
from steward.observability import new_trace_id
from steward.policy.approvals import ApprovalQueue
from steward.policy.audit import AuditRecord, InMemoryAuditLog
from steward.policy.engine import PolicyEngine
from steward.policy.execute import ExecutionGate
from steward.review.offline import build_offline_council
from steward.triage.dedup import DuplicateDetector, InMemoryVectorStore
from steward.triage.ingest import normalize_issue
from steward.triage.models import NormalizedIssue

DEMO_REPO = "stewardbot/demo-shop"
_DEMO_DIR = Path(__file__).resolve().parents[2] / "demo"
_CHECKOUT = _DEMO_DIR / "shop" / "checkout.py"
_CHECKOUT_REL = "shop/checkout.py"

_BUGGY_LINE = "    return subtotal + subtotal * (percent / 100.0)"
_FIXED_LINE = "    return subtotal - subtotal * (percent / 100.0)"

_PROOF_TEST = (
    "import unittest\n"
    "from shop.checkout import apply_discount\n\n"
    "class T(unittest.TestCase):\n"
    "    def test_discount_reduces_total(self):\n"
    "        self.assertEqual(apply_discount(100.0, 10.0), 90.0)\n"
)


# --- the proof, run against the demo's real code (in-process, no Docker) -------


def _discount_holds(source: str) -> bool:
    """Exec ``source`` and check the proof: a 10% discount on 100 yields 90."""
    namespace: dict[str, object] = {}
    exec(compile(source, _CHECKOUT_REL, "exec"), namespace)
    apply_discount = namespace["apply_discount"]
    return apply_discount(100.0, 10.0) == 90.0  # type: ignore[operator]


def _fix_diff(source: str) -> str:
    """Build a clean unified diff flipping the buggy ``+`` to ``-``."""
    lines = source.split("\n")
    i = lines.index(_BUGGY_LINE)
    context = lines[i - 1]
    start = i  # 1-based line number of the context line
    return (
        f"--- a/{_CHECKOUT_REL}\n+++ b/{_CHECKOUT_REL}\n"
        f"@@ -{start},2 +{start},2 @@\n"
        f" {context}\n-{_BUGGY_LINE}\n+{_FIXED_LINE}\n"
    )


# --- graph seams: deterministic, offline, grounded in the demo code -----------


class _DemoReproducer:
    def __init__(self, source: str) -> None:
        self._source = source
        self._offline = OfflineReproducer()

    def reproduce(self, issue: NormalizedIssue) -> ReproOutcome:
        verdict = self._offline.reproduce(issue).verdict
        if verdict is not ReproVerdict.REPRODUCED:
            return ReproOutcome(verdict=verdict, summary="insufficient or non-deterministic report")
        # Grounded: the proof actually fails on the current code.
        failed = not _discount_holds(self._source)
        return ReproOutcome(
            verdict=ReproVerdict.REPRODUCED if failed else ReproVerdict.COULD_NOT_REPRODUCE,
            summary="apply_discount adds the discount instead of subtracting it",
            evidence=None,
        )


class _DemoHypothesizer:
    def hypothesize(self, state: GraphState) -> str:
        return "apply_discount uses '+' where it should use '-' for the percentage discount"


class _DemoPatcher:
    def __init__(self, source: str) -> None:
        self._source = source

    def propose(self, state: GraphState) -> ProposedPatch:
        return ProposedPatch(
            diff=_fix_diff(self._source),
            proof_test=_PROOF_TEST,
            proof_test_path="tests/test_discount_proof.py",
            rationale="Subtract the discount from the subtotal instead of adding it.",
        )


class _DemoTester:
    """Applies the patch in-memory and runs the proof before/after, in-process."""

    def __init__(self, source: str) -> None:
        self._source = source

    def run_proof(self, state: GraphState):
        from steward.sandbox import SandboxResult

        patch = state.patch
        assert patch is not None
        failed_before = not _discount_holds(self._source)
        patched = apply_patch({_CHECKOUT_REL: self._source}, patch.diff)[_CHECKOUT_REL]
        passed_after = _discount_holds(patched)
        proven = failed_before and passed_after
        return SandboxResult(
            passed=proven,
            exit_code=0 if proven else 1,
            timed_out=False,
            duration_s=0.0,
            stdout="proof: failed on current code, passed after the fix"
            if proven
            else "proof not established",
            stderr="",
            image="demo:in-process",
            command="python -m unittest tests.test_discount_proof",
        )


class _NoOpGitHub:
    """A GitHub client that is never called: the demo runs dry-run only."""

    def create_draft_pull_request(self, **_: object) -> PullRequestRef:  # pragma: no cover
        raise AssertionError("demo is dry-run: GitHub must never be called")

    def add_labels(self, **_: object) -> None:  # pragma: no cover
        raise AssertionError("demo is dry-run: GitHub must never be called")


# --- orchestration ------------------------------------------------------------


class IssueReport(BaseModel):
    number: int
    title: str
    triage: str
    disposition: str
    duplicate_of: int | None = None
    pr_branch: str | None = None
    council: str | None = None


class DemoResult(BaseModel):
    repo: str
    dry_run: bool
    issues: list[IssueReport]
    proposed_pr_body: str | None = None
    audit: list[str]


def _load_issues() -> list[NormalizedIssue]:
    payloads = json.loads((_DEMO_DIR / "issues.json").read_text(encoding="utf-8"))
    issues = []
    for p in payloads:
        issues.append(
            normalize_issue(
                {
                    "number": p["number"],
                    "title": p["title"],
                    "body": p["body"],
                    "state": "open",
                    "created_at": "2026-06-16T00:00:00Z",
                    "updated_at": "2026-06-16T00:00:00Z",
                }
            )
        )
    return issues


def run_demo() -> DemoResult:
    """Run one full dry-run cycle over the seeded demo issues and report it."""
    settings = Settings(_env_file=None, STEWARD_GITHUB_REPO=DEMO_REPO)  # type: ignore[call-arg]
    source = _CHECKOUT.read_text(encoding="utf-8")
    audit = InMemoryAuditLog()
    engine = PolicyEngine(target_repo=DEMO_REPO)
    queue = ApprovalQueue(audit_log=audit)
    gate = ExecutionGate(settings=settings, audit_log=audit)
    opener = DraftPullRequestOpener(engine=engine, queue=queue, gate=gate, github=_NoOpGitHub())

    deps = StewardDeps(
        classifier=OfflineClassifier(),
        reproducer=_DemoReproducer(source),
        hypothesizer=_DemoHypothesizer(),
        patcher=_DemoPatcher(source),
        tester=_DemoTester(source),
        pr_opener=opener,
        # The grounded fix passes through the multi-agent review council (#55)
        # before any PR — deterministic offline panel, no keys required.
        council=build_offline_council(),
    )
    graph = build_graph(deps)

    issues = _load_issues()
    detector = DuplicateDetector(HashingTfEmbedder(), InMemoryVectorStore(), threshold=0.25)
    detector.index(issues)

    reports: list[IssueReport] = []
    proposed_body: str | None = None
    for issue in issues:
        report = detector.find_duplicates(issue)
        earlier = [c for c in report.candidates if c.issue_number < issue.number]
        if earlier:
            reports.append(
                IssueReport(
                    number=issue.number,
                    title=issue.title,
                    triage="duplicate",
                    disposition=f"duplicate of #{earlier[0].issue_number} — would comment + label",
                    duplicate_of=earlier[0].issue_number,
                )
            )
            continue

        state = run_issue(graph, issue, trace_id=new_trace_id(), thread_id=f"demo-{issue.number}")
        disposition, branch = _describe(state)
        triage_label = (
            "needs-info"
            if state.triage and state.triage.needs_info
            else (state.triage.category.value if state.triage else "?")
        )
        if state.outcome is GraphOutcome.FIX_PROPOSED:
            proposed_body = render_pr_body(state)
            # Show the full gated path in dry-run: approve, then execute (dry-run
            # writes an audit record and never calls GitHub).
            pending = queue.pending()
            if pending:
                approved = queue.approve(pending[0].approval_id, by="demo-maintainer")
                opener.execute_approved(approved, trace_id=state.trace_id)
        council = (
            f"{state.council_review.verdict.label} — {state.council_review.summary}"
            if state.council_review
            else None
        )
        reports.append(
            IssueReport(
                number=issue.number,
                title=issue.title,
                triage=triage_label,
                disposition=disposition,
                pr_branch=branch,
                council=council,
            )
        )

    return DemoResult(
        repo=DEMO_REPO,
        dry_run=settings.dry_run,
        issues=reports,
        proposed_pr_body=proposed_body,
        audit=[_audit_line(r) for r in audit.records()],
    )


def _describe(state: GraphState) -> tuple[str, str | None]:
    if state.outcome is GraphOutcome.FIX_PROPOSED:
        branch = state.pr.branch if state.pr else None
        return ("verified fix — draft PR proposed (dry-run, pending approval)", branch)
    if state.outcome is GraphOutcome.NEEDS_INFO:
        return ("needs-info — asked for more detail, no action", None)
    if state.outcome is GraphOutcome.TRIAGED_NON_BUG:
        return ("triaged (non-bug) — no fix attempted", None)
    return (state.outcome.value, None)


def _audit_line(record: AuditRecord) -> str:
    mode = "dry-run" if record.dry_run else "LIVE"
    return (
        f"#{record.seq} {record.actor} · {record.action.kind.value} · "
        f"{record.decision.verdict.value} · {mode} · {record.note or ''}".strip()
    )


def _force_utf8_stdout() -> None:
    """Make stdout UTF-8 so the report's ``·`` and ``🤖`` survive a cp1252 console.

    The proposed PR body and audit lines carry non-ASCII characters; on a default
    Windows console (cp1252) ``print`` would raise ``UnicodeEncodeError``. Reconfigure
    if we can, otherwise fall back to replacement so the demo never crashes on output.
    """
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        with suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _force_utf8_stdout()
    result = run_demo()
    print(f"\n=== Steward demo · {result.repo} · dry_run={result.dry_run} ===\n")
    for r in result.issues:
        print(f"  #{r.number} [{r.triage}] {r.title}")
        print(f"      -> {r.disposition}")
        if r.council:
            print(f"      review council: {r.council}")
    if result.proposed_pr_body:
        print("\n--- proposed draft PR (NOT opened; dry-run) ---")
        print("\n".join("  " + line for line in result.proposed_pr_body.splitlines()))
    print("\n--- audit log (every gated decision) ---")
    for line in result.audit:
        print("  " + line)
    print("\nNo external calls were made. Steward never merges.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
