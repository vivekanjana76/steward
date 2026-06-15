# Steward

**Steward** is an autonomous open-source maintainer's teammate. Pointed at a
repository it has rights to, it works the backlog like a careful junior
maintainer: it **triages** issues, **reproduces** bugs in a sandbox, proposes
**fixes** as **draft** pull requests with a test that proves them, and keeps
docs in sync.

Every action is gated by an explicit **trust policy** and a **human approval**
step. Steward never merges, never force-pushes, and never acts outside its
policy — and it proves its reliability with published eval scores. See
[`CLAUDE.md`](CLAUDE.md) for the full operating manual.

> Status: early scaffolding. Capabilities are built milestone-by-milestone
> (M1–M7); see the GitHub issues and milestones.

## Development

Requires **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/). `just` is
optional — every task has a raw-command equivalent.

```bash
uv sync                 # create the venv and install deps (incl. dev tools)
```

| Task         | `just`      | Raw command(s)                                                          |
| ------------ | ----------- | ----------------------------------------------------------------------- |
| Lint + types | `just lint` | `uv run ruff check . && uv run ruff format --check . && uv run pyright` |
| Tests        | `just test` | `uv run pytest`                                                         |
| Stack up     | `just up`   | `docker compose up --build`                                             |
| API service  | `just api`  | `uv run uvicorn steward.api.app:app --reload --port 8000`              |

Copy [`.env.example`](.env.example) to `.env` and fill in keys as needed
(`.env` is git-ignored; never commit secrets).

## Model access

Every Anthropic call goes through one module —
[`src/steward/llm/client.py`](src/steward/llm/client.py) — so models are
swappable in a single place (CLAUDE.md §4). Callers pick a logical **role**, not
a model id:

| Role                          | Model              |
| ----------------------------- | ------------------ |
| `routine`                     | `claude-sonnet-4-6` |
| `planner` / `patch` / `verifier` | `claude-opus-4-8`   |

`ModelClient.complete` returns normalized text + token usage;
`ModelClient.structured` validates the reply into a caller-supplied Pydantic
model via forced tool use. Set `ANTHROPIC_API_KEY` to use it live.

## Triage

Incoming issues are turned into typed, validated snapshots by
[`src/steward/triage/`](src/steward/triage/).
`normalize_issue(payload, comments)` maps a raw GitHub issue onto an immutable
`NormalizedIssue`. Because issue text is **untrusted input** (CLAUDE.md §5), all
free text is sanitized at this boundary — invisible/bidi Unicode and control
characters are stripped — and prompt-injection heuristics run once across the
title, body, and comments, recording any hits in `injection_signals` (evidence
to act cautiously, never proof).

`IssueClassifier` then labels each issue as **bug / feature / question** with a
confidence and short rationale via the central model client (structured output).
Low-confidence results route to `status:needs-info` rather than guessing, and
the issue is presented to the model strictly as data to resist prompt injection.

`DuplicateDetector` finds likely-duplicate issues using embeddings + cosine
similarity. Issues are embedded with a **pinned** model (`voyage-3`, 1024-dim;
ADR-0002) behind an `Embedder` interface, and stored behind a `VectorStore`
interface — an in-memory store ships now; a pgvector adapter slots in later
without changing callers. A pair is only ever reported as a duplicate when its
score clears a **documented, configurable threshold**
(`DEFAULT_SIMILARITY_THRESHOLD`, currently `0.85`); the result is
evidence-bearing — a linked issue number and its score — never an unsupported
claim, and *no duplicate found* is a valid grounded outcome (CLAUDE.md §1).
Set `VOYAGE_API_KEY` and install the extra (`uv sync --extra dedup`) to use it
live; unit tests run against an injected stub, no network.

Applying a triage outcome to the real issue (`steward.triage.apply`) is
Steward's first world-mutating capability, so the full trust machinery
applies: the proposed comment + labels are **greylist actions** queued for
human approval and executed only through the `ExecutionGate` — dry-run by
default, audit-logged either way. The rendered comment is evidence-bearing
(confidence, rationale, duplicate scores with linked issues) and every piece
of Steward-authored content carries the `ai-generated` label.

## Trust policy

No tool call that mutates the outside world executes without passing the
policy engine first ([`src/steward/policy/`](src/steward/policy/), CLAUDE.md
§1/§3). Every proposed action is a typed `Action` classified by a pure,
deterministic `classify()` into exactly one list:

| List      | Verdict            | Examples                                              |
| --------- | ------------------ | ----------------------------------------------------- |
| whitelist | allow              | read issue, search code, find duplicates, sandboxed tests |
| greylist  | require approval   | comment, apply labels, create/push branch, open draft PR |
| blacklist | deny, always       | merge, force-push, push to default branch, delete branch |

Any action aimed at a repository other than the configured
`STEWARD_GITHUB_REPO` is denied regardless of kind. Enforcement is
structural: executors require an `AuthorizedAction`, which only
`PolicyEngine.authorize` produces, and it raises for anything but an `allow`
verdict — there is no override parameter, by design. Every decision carries
the rule that fired and a human-readable reason for the audit log.

Every proposed or executed action (including dry-runs and denials) is recorded
in an **append-only audit log** (`steward.policy.audit`). Records are frozen,
carry the `trace_id` of their Langfuse trace, and form a SHA-256 **hash
chain** anchored at a genesis hash — rewriting, dropping, or reordering any
historical entry breaks `verify_chain`, and the JSONL backend refuses to open
a tampered file. The store exposes `append` and `records`, nothing else.

Greylist actions pause for **explicit human approval**
(`steward.policy.approvals`). `ApprovalQueue.request` accepts only a
`require_approval` decision — a deny verdict can never even be queued — and
`approve` is the sole producer of `ApprovedAction`, the execution proof
executors demand for greylist work. Rejected and expired (default TTL 24 h)
requests are terminal and never execute; every transition is audit-logged
with the human actor (`human:<login>`) and the `trace_id`.

All execution funnels through the **`ExecutionGate`** (`steward.policy.execute`).
**Dry-run is the global default**: going live requires *both*
`STEWARD_DRY_RUN=false` *and* the specific action kind opted in via
`STEWARD_LIVE_ACTIONS` — and the dry-run path never invokes the executor, it
only writes an audit record. The gate does not trust proof objects: it
**re-classifies every action** and demands the proof type match the fresh
verdict, so even a forged `AuthorizedAction` wrapping a blacklisted action is
refused (and the refusal audited). The safety suite
(`tests/test_policy_safety.py`) pins all of this exhaustively; its failures
are release blockers — never weaken it to make a change pass.

## Observability

Every node and tool call can be wrapped in a span via
[`src/steward/observability/`](src/steward/observability/), capturing latency,
token usage, cost, and a `trace_id` for the audit log (CLAUDE.md §11):

```python
from steward.observability import get_tracer

tracer = get_tracer()
with tracer.span("triage", trace_id=trace_id) as span:
    span.record_usage(input_tokens=120, output_tokens=30)
    span.set_cost(0.0021)
```

Tracing is **Langfuse-backed when configured and a no-op otherwise** — it never
makes network calls or raises when `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`
are absent, so local dev and CI are unaffected. Enable the live backend with the
optional extra:

```bash
uv sync --extra observability   # installs langfuse; set the keys in .env
```

## Sandboxed test runs

Reproduction and fix-verification depend on running a repo's tests and trusting
the result, so the run must be **isolated** (CLAUDE.md §4/§12). The sandbox
([`src/steward/sandbox/`](src/steward/sandbox/)) runs a test command in a
**disposable Docker container**: the checkout is bind-mounted **read-only** and
copied to a writable workdir *inside* the container (the host files are never
mutated), **networking is disabled by default**, and memory and time are
bounded. It returns a typed `SandboxResult` (`passed`, exit code, captured
stdout/stderr, duration, `timed_out`) — `passed` is true only on a clean exit
within the timeout, so a failure or timeout carries its own evidence.

Running tests is a **whitelist** action precisely because it is sandboxed. The
orchestration is split from the container mechanics behind a `ContainerBackend`
protocol, so the runner is unit-tested against a fake backend with no Docker;
the `docker` SDK is a lazy, optional extra (`uv sync --extra sandbox`) needed
only for live runs. Two integration tests (gated by `STEWARD_SANDBOX_IT=1` and a
reachable daemon) prove a real run passes and that networking is truly disabled.

## Fix generation

For a reproduced, well-scoped bug, [`src/steward/fix/`](src/steward/fix/)
generates a candidate fix and proves it (CLAUDE.md §1):

- **`PatchGenerator`** (the graph's `Patcher`) asks the model — the **patch**
  role → Opus, via the one central client — for the smallest unified diff plus a
  proof test, as structured output. A diff that is malformed or **does not apply
  cleanly is rejected here**, never downstream.
- **`apply_patch`** is a small, pure, fully unit-tested unified-diff applier: it
  returns the patched contents or raises `PatchDoesNotApply` on any context
  mismatch — Steward never applies a patch it cannot place exactly.
- **`SandboxProofTester`** (the graph's `Tester`) proves the patch by a genuine
  **fail-before / pass-after** run in the sandbox: it runs the proof test
  unpatched (expecting failure) and again with the diff applied (expecting
  success), and reports `passed` **only when both hold** — a proof test that
  already passes without the fix proves nothing and is rejected. The host
  checkout is never mutated (all work happens in temp copies, then the
  container).

## Agent graph

The capabilities above are orchestrated by a stateful **LangGraph** graph
([`src/steward/graph/`](src/steward/graph/), ADR-0001) that models the cycle from
CLAUDE.md §3:

```
triage → route → reproduce → hypothesize → patch → test → VERIFY → open draft PR
```

Two properties are structural, not incidental:

- **Backtracking is real.** A failed reproduction or a non-bug routes the run to
  a terminal state; a *failing proof test* routes **back** to re-hypothesize
  (bounded by `max_attempts`), never forward. The graph gives up honestly rather
  than proposing an unproven fix.
- **VERIFY gates every claim.** No "fixed" verdict — and no draft PR — is emitted
  unless the bug was reproduced, a patch exists, and its proof test **passed** in
  the sandbox (CLAUDE.md §1).

State is one typed `GraphState` (Pydantic) at every node boundary, with
checkpointing enabled so a run is resumable and inspectable. The graph owns
control flow only; the work is delegated to capability seams
(`Reproducer`, `Hypothesizer`, `Patcher`, `Tester`, `PullRequestOpener`) — triage
is wired to the real classifier, and the reproduce/patch/PR implementations land
in their own issues (#15, #16) and route through the policy engine there. This
lets the full orchestration be integration-tested today against deterministic
fakes — no model, Docker, or network.

## API service

A thin **FastAPI** service ([`src/steward/api/`](src/steward/api/)) sits between
the dashboard and the policy core (CLAUDE.md §3/§13). It is read-mostly and adds
**no new world-mutating capability** — it projects the existing audit log and
approval queue into UI-facing views and routes approve/reject through the
`ApprovalQueue`, so every policy invariant (greylist needs approval,
rejected/expired are terminal, every transition audited) holds exactly as
elsewhere.

| Endpoint                                | Purpose                                              |
| --------------------------------------- | ---------------------------------------------------- |
| `GET /api/health`                       | Liveness + safety posture (env, dry-run, target repo) |
| `GET /api/actions`                      | Append-only audit log, most-recent-first             |
| `GET /api/approvals`                    | Pending greylist approval requests                   |
| `POST /api/approvals/{id}/approve`      | Approve via the queue (audited as `human:<by>`)      |
| `POST /api/approvals/{id}/reject`       | Reject (terminal — never executes)                   |
| `GET /api/scorecard`                    | Published eval metrics, or an honest "not yet measured" |

Run it with `just api` (raw: `uv run uvicorn steward.api.app:app --reload`) and
open `http://localhost:8000/docs` for the OpenAPI UI. Handlers are thin and the
audit log + approval queue are in-memory for now (a durable backend slots in
behind the same protocols). Set `STEWARD_SEED_DEMO=true` to populate a small
slice of **real** policy decisions so the dashboard demo is non-empty before the
live agent is wired.

## Dashboard

The maintainer's **command center** lives in [`dashboard/`](dashboard/) — a dark,
glassmorphic Next.js (App Router) + Tailwind UI over the API: the live audit-log
**Activity Stream**, the greylist **Approval Queue** (approve/reject through the
policy queue, never a direct mutation), and the eval **Scorecard**. It reads the
API and degrades to an honest "core offline" state when it can't.

```bash
STEWARD_SEED_DEMO=true just api      # terminal 1 (from repo root)
cd dashboard && npm install && npm run dev   # terminal 2 -> http://localhost:3000
```

See [`dashboard/README.md`](dashboard/README.md) for details.

## Architecture & decisions

A full architecture section and demo land in M7. Design decisions are recorded
as ADRs in [`docs/adr/`](docs/adr/). Recommended development tooling — MCP
servers and the checked-in agent skills — is documented in
[`docs/dev-tooling.md`](docs/dev-tooling.md).
