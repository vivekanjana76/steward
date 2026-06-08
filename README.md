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

## Triage

Incoming issues are turned into typed, validated snapshots by
[`src/steward/triage/`](src/steward/triage/).
`normalize_issue(payload, comments)` maps a raw GitHub issue onto an immutable
`NormalizedIssue`. Because issue text is **untrusted input** (CLAUDE.md §5), all
free text is sanitized at this boundary — invisible/bidi Unicode and control
characters are stripped — and prompt-injection heuristics run once across the
title, body, and comments, recording any hits in `injection_signals` (evidence
to act cautiously, never proof). Classification and dedup build on this model.

## Architecture & decisions

A full architecture section and demo land in M7. Design decisions are recorded
as ADRs in [`docs/adr/`](docs/adr/).
