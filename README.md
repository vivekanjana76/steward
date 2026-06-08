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

## Architecture & decisions

A full architecture section and demo land in M7. Design decisions are recorded
as ADRs in [`docs/adr/`](docs/adr/).
