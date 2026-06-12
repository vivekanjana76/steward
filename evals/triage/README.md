# Triage evals — classification

Versioned, labeled cases for the issue classifier (`steward.triage.classify`).
The scoring harness (classification accuracy / F1, plus the
`status:needs-info` routing and injection-surfacing checks) lands with the
triage metrics work (**#20 / M6**); this directory currently holds the **data**
those metrics run against, committed so it can grow case-by-case.

> Every regression that's ever found becomes a permanent eval case (CLAUDE.md
> §10). Add the failing issue here with its expected label — never weaken or
> delete a case to make a run pass.

## `classification_cases.jsonl`

One JSON object per line:

| Field                     | Type   | Required | Meaning                                                                 |
| ------------------------- | ------ | -------- | ----------------------------------------------------------------------- |
| `id`                      | string | yes      | Stable, unique case id.                                                 |
| `title`                   | string | yes      | Issue title (raw; the harness sanitizes via ingestion).                 |
| `body`                    | string | yes      | Issue body (raw).                                                       |
| `expected_category`       | string | no\*     | One of `bug` / `feature` / `question`.                                  |
| `expected_needs_info`     | bool   | no\*     | `true` when the case is too thin to classify and must route to `status:needs-info`. |
| `expected_injection_signal` | string | no     | An injection signal that ingestion must surface (e.g. `instruction-override`). |
| `notes`                   | string | no       | Why the case exists / what it guards against.                           |

\* Each case sets exactly one of `expected_category` or `expected_needs_info`.

The harness will build a `NormalizedIssue` from each case, run `IssueClassifier`
against a fixed model, and assert the expected category (or needs-info routing)
and any expected injection signal.
