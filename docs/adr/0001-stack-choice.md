# ADR-0001: Technology stack

- **Status:** Accepted
- **Date:** 2026-06-03
- **Deciders:** Steward maintainers

## Context

Steward is an autonomous open-source maintainer's teammate: it triages issues,
reproduces bugs in a sandbox, proposes fixes as draft PRs, and does all of this
behind a trust policy with human approval. The project's non-negotiables
(bounded autonomy, grounded-or-silent, measured, observable, reproducible —
`CLAUDE.md` §1) drive the stack as much as raw capability does. We need to fix
the foundational technology choices before building features so every later PR
builds on the same ground.

## Decision

Adopt the stack defined in `CLAUDE.md` §4:

- **Languages:** Python 3.12+ for the agent / API / MCP server; TypeScript
  (Next.js, App Router) for the dashboard.
- **Orchestration:** LangGraph — a stateful graph with checkpointing and
  human-in-the-loop interrupts, which directly models our triage → reproduce →
  hypothesize → patch → test → verify cycle with backtracking.
- **Model access:** Anthropic API through a single client module
  (`steward.llm.client`). Sonnet for routine nodes; Opus for planner, patch
  generator, and verifier. Model ids live in one place and are swappable.
- **Typed contracts:** Pydantic v2 on every node boundary, tool I/O, and API
  schema.
- **Sandboxing:** Docker — repo test runs happen in disposable containers,
  never on the host.
- **Retrieval / dedup:** embeddings + vector similarity (pgvector on Supabase or
  a local store); the embedding model is pinned and documented.
- **MCP server:** FastMCP (Python).
- **Evals:** SWE-bench (Verified/Lite subset) for fix success; versioned labeled
  sets for triage and reproduction; LLM-as-judge + deterministic checks.
- **Observability:** Langfuse (traces, token cost, latency per action).
- **API/Dashboard:** FastAPI + uvicorn; Next.js + Tailwind.
- **Quality gates:** ruff (lint + format), pyright (types), pytest
  (+ pytest-asyncio).
- **Project / packaging:** `uv` with a `src/` layout; `hatchling` build backend.
- **Task runner:** `just`, with a raw-command equivalent documented for every
  recipe so Windows users without `just` are never blocked.
- **CI/CD:** GitHub Actions.

Dependencies are pinned; heavy dependencies and framework additions require
their own ADR and PR justification.

## Consequences

- **Positive:** One model-selection chokepoint; typed boundaries catch contract
  drift early; Docker isolation makes sandboxed runs safe; LangGraph gives us
  checkpointing and HITL interrupts for free; `uv` yields fast, reproducible
  installs; the eval stack lets us publish honest scores.
- **Negative / costs:** Several moving parts (Docker, a vector store, Langfuse,
  two languages) raise local-setup complexity — mitigated by `just up` and
  documented raw commands. LangGraph and FastMCP are evolving; we pin versions
  and isolate their surfaces.
- **Revisit if:** the vector-store choice (pgvector vs. local) or the LangGraph
  dependency proves limiting — each change would be its own ADR.
