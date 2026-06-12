"""Unit tests for embeddings-based duplicate detection.

The Voyage embedding backend is replaced by a deterministic in-memory stub, so a
real :class:`DuplicateDetector` exercises the actual cosine-similarity retrieval
and grounding-threshold path with no network (CLAUDE.md §9). The stub maps each
issue to a fixed unit vector keyed by topic, so "duplicate" pairs are genuinely
near and unrelated issues are genuinely far.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from steward.config import Settings
from steward.triage.dedup import (
    DEFAULT_SIMILARITY_THRESHOLD,
    VOYAGE_EMBED_DIM,
    DedupError,
    DuplicateDetector,
    DuplicateReport,
    InMemoryVectorStore,
    StoredIssue,
    VoyageEmbedder,
    build_embedder,
    cosine_similarity,
    issue_text,
)
from steward.triage.models import IssueState, NormalizedIssue

# A tiny topic space: each issue's text is matched to a unit basis vector. Texts
# sharing a topic embed to (nearly) the same direction -> high cosine similarity.
_TOPICS: dict[str, tuple[float, float, float]] = {
    "login": (1.0, 0.0, 0.0),
    "darkmode": (0.0, 1.0, 0.0),
    "export": (0.0, 0.0, 1.0),
}


def _topic_for(text: str) -> tuple[float, float, float]:
    lowered = text.lower()
    if "log in" in lowered or "login" in lowered or "sign in" in lowered:
        return _TOPICS["login"]
    if "dark" in lowered or "theme" in lowered:
        return _TOPICS["darkmode"]
    if "csv" in lowered or "export" in lowered:
        return _TOPICS["export"]
    return (0.5, 0.5, 0.5)  # generic, far from every topic axis


class _StubEmbedder:
    """Deterministic embedder: text -> a fixed unit vector by topic, no network."""

    def __init__(self, *, model: str = "stub-embed") -> None:
        self._model = model
        self.calls: list[tuple[tuple[str, ...], str]] = []

    @property
    def model(self) -> str:
        return self._model

    def embed(
        self, texts: Sequence[str], *, input_type: str = "document"
    ) -> list[tuple[float, ...]]:
        self.calls.append((tuple(texts), input_type))
        return [_topic_for(t) for t in texts]


def _issue(number: int, title: str, body: str = "") -> NormalizedIssue:
    now = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    return NormalizedIssue(
        number=number,
        title=title,
        body=body,
        author="octocat",
        state=IssueState.OPEN,
        created_at=now,
        updated_at=now,
    )


def _detector(**kwargs: float | int) -> tuple[DuplicateDetector, _StubEmbedder]:
    embedder = _StubEmbedder()
    detector = DuplicateDetector(embedder, InMemoryVectorStore(), **kwargs)  # type: ignore[arg-type]
    return detector, embedder


# --- cosine_similarity --------------------------------------------------------


def test_cosine_identical_and_orthogonal() -> None:
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)
    assert cosine_similarity((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(-1.0)


def test_cosine_is_scale_invariant() -> None:
    assert cosine_similarity((1.0, 2.0), (2.0, 4.0)) == pytest.approx(1.0)


def test_cosine_zero_vector_is_zero_not_error() -> None:
    assert cosine_similarity((0.0, 0.0), (1.0, 1.0)) == 0.0


def test_cosine_dimension_mismatch_raises() -> None:
    with pytest.raises(DedupError):
        cosine_similarity((1.0, 0.0), (1.0, 0.0, 0.0))


# --- InMemoryVectorStore ------------------------------------------------------


def test_store_query_orders_by_descending_score() -> None:
    store = InMemoryVectorStore()
    store.add(
        [
            StoredIssue(number=1, title="a", embedding=(1.0, 0.0)),
            StoredIssue(number=2, title="b", embedding=(0.0, 1.0)),
            StoredIssue(number=3, title="c", embedding=(0.9, 0.1)),
        ]
    )
    results = store.query((1.0, 0.0), top_k=2)
    assert [r.number for r in results] == [1, 3]
    assert results[0].score == pytest.approx(1.0)


def test_store_add_overwrites_same_number() -> None:
    store = InMemoryVectorStore()
    store.add([StoredIssue(number=1, title="old", embedding=(1.0, 0.0))])
    store.add([StoredIssue(number=1, title="new", embedding=(0.0, 1.0))])
    assert len(store) == 1
    assert store.query((0.0, 1.0), top_k=1)[0].title == "new"


def test_store_query_rejects_nonpositive_top_k() -> None:
    store = InMemoryVectorStore()
    store.add([StoredIssue(number=1, embedding=(1.0, 0.0))])
    with pytest.raises(DedupError):
        store.query((1.0, 0.0), top_k=0)


# --- DuplicateDetector --------------------------------------------------------


def test_finds_duplicate_above_threshold_with_evidence() -> None:
    detector, _ = _detector()
    detector.index(
        [
            _issue(101, "Login button does nothing on Firefox"),
            _issue(201, "Add a dark mode theme"),
            _issue(301, "Export the report as CSV"),
        ]
    )

    report = detector.find_duplicates(_issue(102, "Cannot log in on Firefox, submit does nothing"))

    assert isinstance(report, DuplicateReport)
    assert report.has_duplicates
    assert report.best_match is not None
    assert report.best_match.issue_number == 101  # same topic = the login issue
    assert report.best_match.score >= report.threshold
    assert report.embedding_model == "stub-embed"


def test_no_duplicate_when_nothing_clears_threshold() -> None:
    detector, _ = _detector()
    detector.index([_issue(201, "Add a dark mode theme")])

    # Different topic (export) -> orthogonal -> score 0, below threshold.
    report = detector.find_duplicates(_issue(301, "Export the report as CSV"))

    assert not report.has_duplicates
    assert report.candidates == ()
    assert report.best_match is None


def test_excludes_the_query_issue_from_its_own_results() -> None:
    detector, _ = _detector()
    issue = _issue(101, "Login button does nothing on Firefox")
    detector.index([issue])

    # The issue is the only thing indexed; it must not be returned as its own dup.
    report = detector.find_duplicates(issue)
    assert not report.has_duplicates


def test_threshold_is_configurable() -> None:
    # The login query vs a dark-mode index entry is orthogonal (score 0). A
    # threshold of 0 (or below) makes even that a "candidate"; the default does not.
    strict, _ = _detector()
    loose, _ = _detector(threshold=-0.5)
    for det in (strict, loose):
        det.index([_issue(201, "Add a dark mode theme")])

    assert not strict.find_duplicates(_issue(101, "Login is broken")).has_duplicates
    assert loose.find_duplicates(_issue(101, "Login is broken")).has_duplicates


def test_index_uses_document_and_query_uses_query_input_type() -> None:
    detector, embedder = _detector()
    detector.index([_issue(101, "Login broken")])
    detector.find_duplicates(_issue(102, "Cannot log in"))

    assert embedder.calls[0][1] == "document"  # index call
    assert embedder.calls[-1][1] == "query"  # find_duplicates call


def test_report_threshold_defaults_to_documented_constant() -> None:
    detector, _ = _detector()
    detector.index([_issue(101, "Login broken")])
    report = detector.find_duplicates(_issue(102, "Cannot log in"))
    assert report.threshold == DEFAULT_SIMILARITY_THRESHOLD


def test_indexing_empty_iterable_is_a_noop() -> None:
    detector, embedder = _detector()
    detector.index([])
    assert embedder.calls == []


def test_issue_text_combines_title_and_body() -> None:
    text = issue_text(_issue(1, "Title here", "Body here"))
    assert "Title here" in text
    assert "Body here" in text


# --- VoyageEmbedder (SDK stubbed) ---------------------------------------------


class _StubVoyageResult:
    def __init__(self, embeddings: list[list[float]]) -> None:
        self.embeddings = embeddings


class _StubVoyageClient:
    def __init__(self, embeddings: list[list[float]]) -> None:
        self._embeddings = embeddings
        self.calls: list[dict[str, object]] = []

    def embed(self, texts: list[str], *, model: str, input_type: str | None = None) -> object:
        self.calls.append({"texts": texts, "model": model, "input_type": input_type})
        return _StubVoyageResult(self._embeddings)


def test_voyage_embedder_validates_dimension_and_passes_model() -> None:
    vec = [0.1] * VOYAGE_EMBED_DIM
    client = _StubVoyageClient([vec, vec])
    embedder = VoyageEmbedder(client=client)

    vectors = embedder.embed(["a", "b"], input_type="query")

    assert len(vectors) == 2
    assert len(vectors[0]) == VOYAGE_EMBED_DIM
    assert client.calls[0]["model"] == "voyage-3"
    assert client.calls[0]["input_type"] == "query"


def test_voyage_embedder_empty_input_skips_backend() -> None:
    client = _StubVoyageClient([])
    assert VoyageEmbedder(client=client).embed([]) == []
    assert client.calls == []


def test_voyage_embedder_wrong_dimension_raises() -> None:
    client = _StubVoyageClient([[0.1, 0.2, 0.3]])  # not VOYAGE_EMBED_DIM
    with pytest.raises(DedupError):
        VoyageEmbedder(client=client).embed(["a"])


def test_voyage_embedder_count_mismatch_raises() -> None:
    client = _StubVoyageClient([[0.1] * VOYAGE_EMBED_DIM])  # one vector for two inputs
    with pytest.raises(DedupError):
        VoyageEmbedder(client=client).embed(["a", "b"])


def test_build_embedder_requires_api_key() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.voyage_api_key is None
    with pytest.raises(DedupError):
        build_embedder(settings)
