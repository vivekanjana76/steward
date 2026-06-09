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

## Architecture & decisions

A full architecture section and demo land in M7. Design decisions are recorded
as ADRs in [`docs/adr/`](docs/adr/).
