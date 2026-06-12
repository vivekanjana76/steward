---
name: steward-pr-loop
description: Run the Steward repo's issue-to-merge workflow - use when picking up a GitHub issue in this repo, opening a PR, or landing a change. Encodes CLAUDE.md §15 (branch naming, quality gates, draft PRs, squash-merge, never committing to main).
---

# Steward PR loop

Work issue-by-issue. Never code without an issue; never commit to `main`.

## 1. Pick or create the issue
- Confirm it has acceptance criteria and a milestone. If not, fix the issue first.
- Issues/labels/PRs go through the **GitHub MCP**; code goes through **local git**.

## 2. Branch off latest main
```
git checkout main && git pull origin main
git checkout -b feat/issue-<NN>-<slug>    # or fix/ chore/ docs/ eval/
```

## 3. Implement in small commits
- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `eval:` ...), one logical change each.
- Tests and eval cases ship in the same PR as the feature — no "tests later".
- Any new world-mutating action: classify it in `steward.policy.engine` (the
  import-time exhaustiveness check forces this) and leave it dry-run.

## 4. Run the gates locally (all must pass)
```
uv run ruff check . ; uv run ruff format --check . ; uv run pyright ; uv run pytest
```
Never weaken an eval case or a safety test (`tests/test_policy_safety.py`) to get green.

## 5. Open a draft PR
- Title in Conventional-Commit style; body must include `Closes #<NN>`,
  what/why, how it was tested, and eval impact (the template enforces this).
- Open as **draft** until self-checks pass and CI is green, then mark ready.

## 6. Land it
- Squash-merge with the PR title as the commit title (the human merges in
  normal operation; Steward the product never merges).
- Delete the branch. If another open PR used it as a **base, retarget that PR
  to `main` first** — deleting a base branch closes its dependent PRs.
- `git checkout main && git pull` and verify the linked issue auto-closed.
