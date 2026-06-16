# Triage evals — classification & duplicate detection

Versioned, labeled cases for the triage capabilities: the issue classifier
(`steward.triage.classify`) and the duplicate detector
(`steward.triage.dedup`). The scoring harness (classification accuracy / F1 and
duplicate-detection precision/recall, plus the `status:needs-info` routing and
injection-surfacing checks) lives in
[`steward.evals`](../../src/steward/evals/) and runs via `just eval`; this
directory holds the **data** those metrics run against, committed so it can grow
case-by-case.

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

## `duplicate_cases.jsonl`

A small corpus of issues, some of which are labeled duplicates of others. One
JSON object per line:

| Field          | Type        | Required | Meaning                                                                          |
| -------------- | ----------- | -------- | -------------------------------------------------------------------------------- |
| `id`           | string      | yes      | Stable, unique case id.                                                          |
| `number`       | int         | yes      | Issue number; the identity used in `DuplicateReport` evidence.                   |
| `title`        | string      | yes      | Issue title (raw).                                                               |
| `body`         | string      | yes      | Issue body (raw).                                                                |
| `duplicate_of` | int \| null | yes      | The `number` of the issue this duplicates, or `null` if it is unique/canonical.  |
| `notes`        | string      | no       | Why the case exists / what it guards against.                                    |

The harness will `index` every case in `DuplicateDetector`, then run
`find_duplicates` for each and measure **precision/recall** of duplicate
retrieval at the documented similarity threshold
(`DEFAULT_SIMILARITY_THRESHOLD` in `steward.triage.dedup`, currently `0.85`):

- a case with `duplicate_of` set should retrieve that issue as a candidate
  (recall), and
- a unique case (`duplicate_of: null`) should retrieve **no** candidate
  (precision) — Steward never claims a duplicate without a score above the
  threshold (grounded-or-silent, CLAUDE.md §1).

The threshold is tuned against this set; record any change in ADR-0002 and
re-baseline. Never weaken or delete a case to make a run pass (CLAUDE.md §10).
