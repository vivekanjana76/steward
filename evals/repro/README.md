# Reproduction-verdict evals

Versioned, labeled bug reports for the **reproduction** capability: each case
has an expected verdict the reproducer must reach. The scoring harness lives in
[`steward.evals`](../../src/steward/evals/) (`steward.evals.repro`) and runs via
`just eval`, which measures **verdict accuracy** (and macro-F1) and gates it
against `evals/baseline.json`.

> Every regression that's ever found becomes a permanent eval case (CLAUDE.md
> §10). Add the failing report here with its expected verdict — never weaken or
> delete a case to make a run pass.

## `repro_cases.jsonl`

One JSON object per line:

| Field              | Type   | Required | Meaning                                                             |
| ------------------ | ------ | -------- | ------------------------------------------------------------------- |
| `id`               | string | yes      | Stable, unique case id.                                             |
| `title`            | string | yes      | Issue title (raw; sanitized via ingestion).                        |
| `body`             | string | yes      | Issue body (raw).                                                  |
| `expected_verdict` | string | yes      | One of `reproduced` / `could_not_reproduce` / `needs_info`.        |
| `notes`            | string | no       | Why the case exists / what it guards against.                      |

The three verdicts mirror `ReproVerdict` (`steward.graph.state`):

- **`reproduced`** — the report has clear, deterministic steps/evidence (a
  failing run could be produced).
- **`could_not_reproduce`** — the behavior is non-deterministic or
  environment-specific (intermittent, "only on my machine", random).
- **`needs_info`** — too little detail to attempt reproduction; ask rather than
  guess (grounded-or-silent, CLAUDE.md §1).

The harness builds a `NormalizedIssue` from each case via real ingestion, runs a
reproducer (the deterministic offline reference until a sandbox-backed one
lands), and scores the verdict against the label.
