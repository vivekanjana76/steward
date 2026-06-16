"""Duplicate-issue detection via embeddings + vector similarity.

Steward must never claim two issues are duplicates without evidence (CLAUDE.md
§1, grounded-or-silent). So detection is purely numeric and falsifiable: every
issue is embedded, candidates are retrieved by cosine similarity, and a pair is
only ever reported as a likely duplicate when its score clears a **documented,
configurable threshold**. The result carries the linked candidate issue and its
score, so a human (or the policy engine) can check the claim.

Three small, swappable pieces, each behind a structural type so the heavy SDK /
storage backend stays an implementation detail (mirrors
:mod:`steward.llm.client`):

* :class:`Embedder` — turns text into vectors. :class:`VoyageEmbedder` is the
  concrete binding to Voyage AI; the embedding model is **pinned and documented**
  (:data:`VOYAGE_EMBED_MODEL` / :data:`VOYAGE_EMBED_DIM`, ADR-0002).
* :class:`VectorStore` — stores embedded issues and returns nearest neighbours by
  score. :class:`InMemoryVectorStore` is the local, dependency-free
  implementation used now; a pgvector adapter can be added behind the same
  Protocol without touching :class:`DuplicateDetector`.
* :class:`DuplicateDetector` — orchestrates the two and applies the grounding
  threshold, emitting an evidence-bearing :class:`DuplicateReport`.

Only :class:`VoyageEmbedder` touches the network; the rest of the module is pure
and import-safe (no SDK construction or env reads at import).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from steward.config import Settings, get_settings
from steward.triage.models import NormalizedIssue

# --- Embedding model: pinned and documented (CLAUDE.md §4, ADR-0002) ----------

# Voyage AI's general-purpose retrieval embedding model and its dimensionality.
# Pinned here so a model change is a single, reviewed edit (never hardcode a
# model name at a call site). Document any change in ADR-0002 and re-baseline the
# duplicate-detection eval (CLAUDE.md §10).
VOYAGE_EMBED_MODEL = "voyage-3"
VOYAGE_EMBED_DIM = 1024

# Above this cosine similarity two issues are reported as likely duplicates.
# Provisional, deliberately conservative starting point; it is calibrated against
# the labeled duplicate set in evals/triage/ when the precision/recall harness
# lands (#20 / M6). Tunable per detector via the constructor.
DEFAULT_SIMILARITY_THRESHOLD = 0.85

# How many nearest neighbours the store returns before thresholding.
DEFAULT_TOP_K = 5

InputType = Literal["document", "query"]


class DedupError(RuntimeError):
    """Raised when duplicate detection cannot be performed (config or shape errors)."""


# --- Embedder -----------------------------------------------------------------


@runtime_checkable
class Embedder(Protocol):
    """Turns text into fixed-dimension vectors.

    ``input_type`` lets a backend embed stored issues (``"document"``) and the
    query issue (``"query"``) asymmetrically when it supports it; backends that
    don't may ignore it. Returns one vector per input string, in order.
    """

    @property
    def model(self) -> str:
        """The pinned embedding model id, recorded for provenance."""
        ...

    def embed(
        self, texts: Sequence[str], *, input_type: InputType = "document"
    ) -> list[tuple[float, ...]]: ...


class _VoyageLike(Protocol):
    """The slice of the Voyage AI SDK that :class:`VoyageEmbedder` uses.

    Depending on this structural type (not the concrete ``voyageai.Client``)
    keeps the SDK an implementation detail and lets tests inject a stub with no
    network access.
    """

    def embed(self, texts: list[str], *, model: str, input_type: str | None = None) -> Any: ...


class VoyageEmbedder:
    """Concrete :class:`Embedder` backed by the Voyage AI client.

    Construct via :func:`build_embedder` in application code; the explicit
    ``client`` argument exists so tests inject a stub and never touch the network.
    The returned vectors are validated to be :data:`VOYAGE_EMBED_DIM`-dimensional
    so a backend/model mismatch fails loudly here rather than corrupting scores.
    """

    def __init__(
        self,
        *,
        client: _VoyageLike,
        model: str = VOYAGE_EMBED_MODEL,
        dimension: int = VOYAGE_EMBED_DIM,
    ) -> None:
        self._client = client
        self._model = model
        self._dimension = dimension

    @property
    def model(self) -> str:
        return self._model

    def embed(
        self, texts: Sequence[str], *, input_type: InputType = "document"
    ) -> list[tuple[float, ...]]:
        """Embed ``texts`` and return one validated vector per input string."""
        if not texts:
            return []
        result = self._client.embed(list(texts), model=self._model, input_type=input_type)
        raw_vectors = getattr(result, "embeddings", None)
        if raw_vectors is None or len(raw_vectors) != len(texts):
            raise DedupError("embedding backend returned a mismatched number of vectors")
        vectors = [tuple(float(x) for x in vec) for vec in raw_vectors]
        for vec in vectors:
            if len(vec) != self._dimension:
                raise DedupError(
                    f"embedding has dimension {len(vec)}, expected {self._dimension} "
                    f"for model {self._model}"
                )
        return vectors


def build_embedder(settings: Settings) -> VoyageEmbedder:
    """Construct a :class:`VoyageEmbedder` from ``settings``.

    Raises :class:`DedupError` if no Voyage API key is configured, so the failure
    is explicit rather than surfacing deep inside the SDK on first call. The
    ``voyageai`` package is imported lazily (it ships in the optional ``dedup``
    extra) so the module stays import-safe without it.
    """
    if not settings.voyage_api_key:
        raise DedupError("VOYAGE_API_KEY is not set; configure it in the environment or .env")
    try:
        import voyageai  # pyright: ignore[reportMissingImports]  # optional 'dedup' extra
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise DedupError(
            "voyageai is not installed; install the 'dedup' extra (uv sync --extra dedup)"
        ) from exc

    return VoyageEmbedder(client=voyageai.Client(api_key=settings.voyage_api_key))


# --- Vector store -------------------------------------------------------------


class StoredIssue(BaseModel):
    """An embedded issue held in the vector store: identity + its vector."""

    model_config = ConfigDict(frozen=True)

    number: int
    title: str = ""
    embedding: tuple[float, ...] = Field(min_length=1)


class ScoredIssue(BaseModel):
    """A stored issue paired with its cosine similarity to a query vector."""

    model_config = ConfigDict(frozen=True)

    number: int
    title: str = ""
    score: float = Field(ge=-1.0, le=1.0)


class VectorStore(Protocol):
    """Stores embedded issues and retrieves nearest neighbours by similarity.

    A deliberately small surface so a local store and a pgvector-backed store are
    interchangeable behind it (CLAUDE.md §4).
    """

    def add(self, issues: Iterable[StoredIssue]) -> None: ...

    def query(self, embedding: Sequence[float], *, top_k: int) -> list[ScoredIssue]: ...


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Return the cosine similarity of two equal-length vectors in ``[-1, 1]``.

    Raises :class:`DedupError` on a dimension mismatch (a corrupt index would
    otherwise produce a silently meaningless score). A zero-magnitude vector
    yields ``0.0`` rather than dividing by zero.
    """
    if len(a) != len(b):
        raise DedupError(f"vector dimension mismatch: {len(a)} vs {len(b)}")
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(math.fsum(x * x for x in a))
    norm_b = math.sqrt(math.fsum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    # Clamp to honor the documented [-1, 1] range: floating-point rounding can
    # nudge identical vectors to 1.0000000000000002, which downstream score
    # fields (bounded at 1.0) would otherwise reject.
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


class InMemoryVectorStore:
    """A local, dependency-free :class:`VectorStore` using exact cosine search.

    Suitable for the demo repo and tests (no Docker/DB). Vectors are kept in
    memory and scored exhaustively, which is fine at issue-tracker scale; the
    pgvector adapter replaces this for large corpora without changing callers.
    Adding an issue with a number already present overwrites it (re-indexing).
    """

    def __init__(self) -> None:
        self._issues: dict[int, StoredIssue] = {}

    def add(self, issues: Iterable[StoredIssue]) -> None:
        """Index ``issues`` by number, overwriting any existing entry."""
        for issue in issues:
            self._issues[issue.number] = issue

    def query(self, embedding: Sequence[float], *, top_k: int) -> list[ScoredIssue]:
        """Return the ``top_k`` indexed issues most similar to ``embedding``.

        Results are sorted by descending score; ties break on issue number for
        determinism. ``top_k`` must be positive.
        """
        if top_k <= 0:
            raise DedupError("top_k must be a positive integer")
        scored = [
            ScoredIssue(
                number=issue.number,
                title=issue.title,
                score=cosine_similarity(embedding, issue.embedding),
            )
            for issue in self._issues.values()
        ]
        scored.sort(key=lambda s: (-s.score, s.number))
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._issues)


# --- Detector -----------------------------------------------------------------


class DuplicateCandidate(BaseModel):
    """One issue judged a likely duplicate of the query, with its evidence."""

    model_config = ConfigDict(frozen=True)

    issue_number: int
    title: str = ""
    score: float = Field(ge=-1.0, le=1.0)


class DuplicateReport(BaseModel):
    """The grounded duplicate-detection result for a single issue.

    ``candidates`` holds only issues scoring at or above ``threshold``, ordered
    most-similar first — each is verifiable evidence (a linked issue number and a
    score), never an unsupported claim. An empty tuple means *no duplicate found*,
    which is a valid, grounded outcome.
    """

    model_config = ConfigDict(frozen=True)

    issue_number: int
    candidates: tuple[DuplicateCandidate, ...] = ()
    threshold: float = Field(ge=-1.0, le=1.0)
    embedding_model: str

    @property
    def has_duplicates(self) -> bool:
        """True when at least one candidate cleared the similarity threshold."""
        return bool(self.candidates)

    @property
    def best_match(self) -> DuplicateCandidate | None:
        """The highest-scoring candidate, or ``None`` when there are none."""
        return self.candidates[0] if self.candidates else None


def issue_text(issue: NormalizedIssue) -> str:
    """Render an issue to the text used for embedding (title then body).

    Kept as one function so indexing and querying embed issues identically.
    """
    return f"{issue.title}\n\n{issue.body}".strip()


class DuplicateDetector:
    """Finds likely-duplicate issues for a query issue, with grounded evidence.

    ``threshold`` is the cosine-similarity floor below which a candidate is *not*
    reported (grounded-or-silent); ``top_k`` bounds how many neighbours are
    considered before thresholding. The query issue itself is always excluded
    from its own results.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        *,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._threshold = threshold
        self._top_k = top_k

    def index(self, issues: Iterable[NormalizedIssue]) -> None:
        """Embed ``issues`` and add them to the vector store for later querying."""
        issues = list(issues)
        if not issues:
            return
        vectors = self._embedder.embed([issue_text(i) for i in issues], input_type="document")
        self._store.add(
            StoredIssue(number=issue.number, title=issue.title, embedding=vector)
            for issue, vector in zip(issues, vectors, strict=True)
        )

    def find_duplicates(self, issue: NormalizedIssue) -> DuplicateReport:
        """Return a grounded :class:`DuplicateReport` for ``issue``.

        Embeds the issue, retrieves the nearest indexed neighbours, drops the
        issue itself and anything below ``threshold``, and reports the rest as
        evidence-bearing candidates.
        """
        (vector,) = self._embedder.embed([issue_text(issue)], input_type="query")
        neighbours = self._store.query(vector, top_k=self._top_k)
        candidates = tuple(
            DuplicateCandidate(issue_number=n.number, title=n.title, score=n.score)
            for n in neighbours
            if n.number != issue.number and n.score >= self._threshold
        )
        return DuplicateReport(
            issue_number=issue.number,
            candidates=candidates,
            threshold=self._threshold,
            embedding_model=self._embedder.model,
        )


def build_duplicate_detector(
    *,
    store: VectorStore | None = None,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
) -> DuplicateDetector:
    """Build a :class:`DuplicateDetector` from process-wide settings.

    Uses a live :class:`VoyageEmbedder` (requires ``VOYAGE_API_KEY``) and, unless
    one is supplied, a fresh :class:`InMemoryVectorStore`.
    """
    embedder = build_embedder(get_settings())
    return DuplicateDetector(
        embedder, store or InMemoryVectorStore(), threshold=threshold, top_k=top_k
    )
