# Patch-review council evals

Versioned, labeled patches for the **multi-agent reviewer council** (#55): each
case is a proposed `diff` (+ optional `proof_test`) with the verdict the council
should reach. The scoring harness lives in
[`steward.evals`](../../src/steward/evals/) (`steward.evals.review`) and runs via
`just eval`, which measures **verdict accuracy** (and macro-F1) and gates it
against `evals/baseline.json`.

> Every regression that's ever found becomes a permanent eval case (CLAUDE.md
> §10). Add the patch here with its expected verdict — never weaken or delete a
> case to make a run pass.

## `review_cases.jsonl`

One JSON object per line:

| Field              | Type   | Required | Meaning                                                          |
| ------------------ | ------ | -------- | ---------------------------------------------------------------- |
| `id`               | string | yes      | Stable, unique case id.                                          |
| `diff`             | string | yes      | The proposed unified diff under review.                          |
| `proof_test`       | string | no       | The test meant to prove the fix.                                 |
| `test_passed`      | bool   | no       | Whether that proof test was shown to pass (default `false`).     |
| `expected_verdict` | string | yes      | One of `approve` / `request_changes` / `block`.                  |
| `notes`            | string | no       | Why the case exists / what it guards against.                    |

The three verdicts mirror `ReviewVerdict` (`steward.review.models`), aggregated
worst-wins across the panel:

- **`approve`** — a focused fix with a real, passing proof test and no risk.
- **`request_changes`** — fixable concerns: no/trivial/failing test, debug
  leftovers, or a diff that changes no code (backtracks the graph).
- **`block`** — a security risk introduced by the diff (an injection sink, a
  hardcoded secret, disabled TLS verification); terminal, no PR.

The harness runs the council (the deterministic **offline** panel until model
keys are set, the live Opus panel after) over each case and scores its verdict
against the label.
