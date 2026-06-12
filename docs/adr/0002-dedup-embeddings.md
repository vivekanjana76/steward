# ADR-0002: Duplicate detection — embedding model & vector store

- **Status:** Accepted
- **Date:** 2026-06-09
- **Deciders:** Steward maintainers
- **Relates to:** #7 (triage duplicate detection), ADR-0001 (stack)

## Context

Triage must detect likely-duplicate issues (#7). Two choices ADR-0001 left open
have to be fixed before building, and both are the kind of decision `CLAUDE.md`
§4/§6 says to pin, document, and record:

1. **Which embedding model?** It must be pinned and documented so similarity
   scores and the eval baseline are reproducible (a silent model swap would
   invalidate the threshold and the precision/recall numbers).
2. **Which vector store?** ADR-0001 allowed "pgvector on Supabase **or** a local
   store". We need similarity search working now, behind the policy that a
   duplicate is never claimed without a score above a documented threshold
   (grounded-or-silent, §1), without first standing up database infrastructure.

This adds one new external dependency (an embeddings SDK), which per ADR-0001
warrants its own ADR.

## Decision

- **Embedding model: Voyage AI `voyage-3`, 1024-dimensional**, via the
  `voyageai` SDK. It is a strong general-purpose retrieval model and is
  Anthropic's recommended embedding partner, so it sits naturally alongside our
  Anthropic-centric stack without introducing a second large-model provider for
  generation. The model id and dimension are pinned as constants
  (`VOYAGE_EMBED_MODEL`, `VOYAGE_EMBED_DIM`) in `steward.triage.dedup` — the
  single place they may change — and embeddings are dimension-validated on the
  way in so a model/backend mismatch fails loudly.
- **`voyageai` ships as an optional `dedup` extra**, not a core dependency, so
  default installs and CI stay light. The SDK is imported lazily inside
  `build_embedder`; all dedup code paths are unit-tested against an injected stub
  with no network (`CLAUDE.md` §9). Install live with `uv sync --extra dedup`
  and set `VOYAGE_API_KEY`.
- **Vector store: a local in-memory store now, behind a `VectorStore`
  Protocol.** `InMemoryVectorStore` does exact cosine search — correct and
  dependency-free at issue-tracker scale, and fully deterministic for tests and
  the demo. The `Embedder` and `VectorStore` abstractions mean a
  **pgvector-on-Supabase** adapter can be added later behind the same interfaces
  without touching `DuplicateDetector` or its callers. That database adapter is
  deferred to when persistence/scale is actually needed (M4+), and will be its
  own PR.
- **Threshold: `DEFAULT_SIMILARITY_THRESHOLD = 0.85`**, configurable per
  detector. This is a deliberately conservative provisional value; it is
  calibrated against the labeled set in `evals/triage/duplicate_cases.jsonl`
  when the precision/recall harness lands (#20 / M6). Changing it requires
  re-baselining the duplicate-detection metric.

## Consequences

- **Positive:** Similarity search works today with zero infra; scores are
  reproducible from a pinned model; the grounding rule is enforced numerically
  (a linked issue number + score is the evidence); swapping in pgvector or a
  different embedding model is a localized change behind an interface and a
  one-line constant edit.
- **Negative / costs:** One more external dependency and API key (Voyage);
  in-memory exact search is O(n) per query and re-embeds on each process start,
  which is fine now but is exactly what the pgvector adapter will replace. The
  `0.85` threshold is unvalidated until the M6 harness calibrates it.
- **Revisit if:** the embedding model is changed (pin a new id + dimension here
  and re-baseline), persistence/scale forces the pgvector adapter, or calibration
  moves the threshold materially.
