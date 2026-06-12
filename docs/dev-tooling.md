# Dev tooling: MCP servers & agent skills

Steward is built *by* agents as much as *for* them (CLAUDE.md §2), so the
development environment matters. This page documents the MCP servers and
agent skills we recommend when working on this repo, and what each is for
**in this project specifically**. Copy [`.mcp.json.example`](../.mcp.json.example)
to `.mcp.json` to enable the servers (`.mcp.json` is git-ignored — never
commit tokens).

> Not to be confused with the **Steward MCP server** (issue #17, milestone
> M5), which is a *product deliverable*. The servers below are development
> tools.

## Recommended MCP servers

| Server | What it's for here | Source |
| ------ | ------------------ | ------ |
| **GitHub** (official) | The repo workflow itself: issues, labels, PRs, reviews, merges. CLAUDE.md §6 mandates issues/PRs go through the GitHub MCP while code goes through local git. | [github/github-mcp-server](https://github.com/github/github-mcp-server) |
| **Context7** | Live, current docs for our fast-moving deps — LangGraph, FastMCP, Langfuse, Pydantic v2 — instead of a model's stale training data. Most useful in M4–M5 (graph + MCP server). | [upstash/context7](https://github.com/upstash/context7) |
| **Playwright** (official) | Drives a real browser via accessibility snapshots. The tool for developing and verifying the Next.js dashboard (#26): exercising the approval queue, traces view, and scorecard end to end. | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) |
| **Langfuse docs MCP** | Public docs server for Langfuse — handy while wiring tracing and cost capture. The authenticated Langfuse data MCP can additionally query *our* traces for debugging once a project exists. | [langfuse.com/docs/docs-mcp](https://langfuse.com/docs/docs-mcp) |

Why these four: GitHub + Context7 + Playwright cover code, docs, and the
browser — the bulk of what an engineering agent touches — and Langfuse covers
the observability surface this project treats as first-class (CLAUDE.md §11).
Add servers sparingly; every enabled server costs context.

## Agent skills

Project skills live in [`.claude/skills/`](../.claude/skills/) and are
checked in, so every contributor's agent follows the same recipes:

- **`steward-pr-loop`** — the issue → branch → gates → draft PR → CI →
  squash-merge loop from CLAUDE.md §15, in executable-recipe form.

Useful built-in/global skills when working here:

- **`/code-review`** before marking a PR ready — catches correctness bugs in
  the diff.
- **`/security-review`** for anything touching the policy engine, sandbox, or
  input sanitization (CLAUDE.md §12).
- **`/verify`** to confirm a change behaves in the running app, not just in
  unit tests.

## Ground rules

- Servers are configured per-developer in `.mcp.json` (git-ignored). The
  example file carries **no secrets**; tokens come from your environment.
- The GitHub token must be scoped to this repo / the demo repo only (least
  privilege, CLAUDE.md §12).
- MCP tool output is **untrusted input** like any other external data —
  the same prompt-injection caution as issue text applies (CLAUDE.md §5).
