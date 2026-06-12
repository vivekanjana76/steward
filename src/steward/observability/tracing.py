"""Tracing primitives with a Langfuse backend and a no-op fallback.

Every Steward run must be traceable — each node, tool call, token count, cost,
and latency (CLAUDE.md §11) — but local development and CI must never break or
make network calls just because Langfuse is not configured. This module
satisfies both: a :class:`Tracer` records spans to a :class:`SpanSink`, and the
sink is chosen at construction time:

* keys present (and the ``langfuse`` package installed) → :class:`LangfuseSink`;
* otherwise → :class:`NoOpSink`, which makes no network calls and never raises.

The span lifecycle (timing, usage/cost capture, error handling, ``trace_id``
propagation) is pure and fully tested; the Langfuse binding is a thin adapter
behind a structural :class:`_LangfuseLike` ``Protocol`` so tests inject a stub
and never touch the network — mirroring the model client (CLAUDE.md §9).

The ``trace_id`` minted here is the same identifier the audit log will carry, so
any decision can later be replayed against its Langfuse trace.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache, wraps
from time import perf_counter
from typing import Any, Literal, Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

from steward.config import Settings, get_settings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def new_trace_id() -> str:
    """Return a fresh, opaque trace identifier shared by spans and the audit log."""
    return uuid4().hex


class SpanRecord(BaseModel):
    """The immutable summary of one finished span, handed to a :class:`SpanSink`.

    Carries everything the audit log and scorecard need: the ``trace_id``, the
    measured ``latency_ms``, token usage and (optional) cost, and whether the
    work succeeded.
    """

    trace_id: str
    name: str
    latency_ms: float = Field(ge=0.0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    status: Literal["ok", "error"] = "ok"
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Span:
    """A unit of traced work in progress.

    Created by :meth:`Tracer.span`; callers enrich it while the work runs
    (:meth:`record_usage`, :meth:`set_cost`, :meth:`set_metadata`) and the
    tracer finalizes it into a :class:`SpanRecord` on exit. Latency is measured
    with a monotonic clock, so it is unaffected by wall-clock changes.
    """

    def __init__(self, name: str, trace_id: str) -> None:
        self.name = name
        self.trace_id = trace_id
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_usd: float | None = None
        self._metadata: dict[str, Any] = {}
        self._start = perf_counter()

    def record_usage(self, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """Add token counts to this span (accumulates across calls)."""
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

    def set_cost(self, cost_usd: float) -> None:
        """Set the span's cost in USD (CLAUDE.md §11: surface cost-per-action)."""
        self._cost_usd = cost_usd

    def set_metadata(self, **fields: Any) -> None:
        """Attach arbitrary, JSON-serializable metadata to the span."""
        self._metadata.update(fields)

    def _finish(self, error: BaseException | None) -> SpanRecord:
        latency_ms = (perf_counter() - self._start) * 1000.0
        return SpanRecord(
            trace_id=self.trace_id,
            name=self.name,
            latency_ms=latency_ms,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cost_usd=self._cost_usd,
            status="error" if error is not None else "ok",
            error=f"{type(error).__name__}: {error}" if error is not None else None,
            metadata=dict(self._metadata),
        )


class SpanSink(Protocol):
    """Where finished spans go. Implementations must never raise to callers."""

    def record(self, record: SpanRecord) -> None:
        """Persist or emit a finished span."""
        ...

    def flush(self) -> None:
        """Flush any buffered spans to the backend."""
        ...


class NoOpSink:
    """A sink that discards spans. The fallback when Langfuse is not configured.

    Guarantees the acceptance contract for the absent-keys path: it performs no
    I/O and never raises.
    """

    def record(self, record: SpanRecord) -> None:
        return None

    def flush(self) -> None:
        return None


class _LangfuseLike(Protocol):
    """The slice of the Langfuse client that :class:`LangfuseSink` depends on.

    Targets the Langfuse v2 low-level API (``client.trace(...)`` →
    ``trace.span(...)`` / ``trace.update(...)``, plus ``client.flush()``).
    Depending on this structural type keeps the SDK an implementation detail and
    lets tests inject a stub.
    """

    def trace(self, **kwargs: Any) -> Any: ...

    def flush(self) -> None: ...


class LangfuseSink:
    """Adapts :class:`SpanRecord` onto a Langfuse client.

    A failure to emit a span must never break the work being traced, so backend
    errors are logged and swallowed (observability is best-effort).
    """

    def __init__(self, client: _LangfuseLike) -> None:
        self._client = client

    def record(self, record: SpanRecord) -> None:
        try:
            trace = self._client.trace(
                id=record.trace_id,
                name=record.name,
                metadata=record.metadata,
            )
            trace.span(
                name=record.name,
                metadata={
                    **record.metadata,
                    "latency_ms": record.latency_ms,
                    "status": record.status,
                    "error": record.error,
                },
                usage={
                    "input": record.input_tokens,
                    "output": record.output_tokens,
                    "total_cost": record.cost_usd,
                },
            )
        except Exception:
            logger.warning("failed to emit span %r to Langfuse", record.name, exc_info=True)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:
            logger.warning("failed to flush spans to Langfuse", exc_info=True)


class Tracer:
    """Records spans to a :class:`SpanSink`.

    Use :meth:`span` as a context manager around any node or tool call, or the
    :func:`traced` decorator for whole functions. Both mint a ``trace_id`` when
    one is not supplied and forward a :class:`SpanRecord` to the sink exactly
    once, including when the wrapped work raises.
    """

    def __init__(self, sink: SpanSink) -> None:
        self._sink = sink

    @contextmanager
    def span(self, name: str, *, trace_id: str | None = None, **metadata: Any) -> Iterator[Span]:
        """Open a span named ``name``; yields the :class:`Span` to enrich."""
        span = Span(name=name, trace_id=trace_id or new_trace_id())
        if metadata:
            span.set_metadata(**metadata)
        try:
            yield span
        except BaseException as exc:
            self._sink.record(span._finish(exc))
            raise
        else:
            self._sink.record(span._finish(None))

    def flush(self) -> None:
        """Flush buffered spans to the backend."""
        self._sink.flush()


def build_tracer(settings: Settings) -> Tracer:
    """Build the tracer for ``settings``.

    Returns a Langfuse-backed tracer only when both Langfuse keys are present and
    the ``langfuse`` package is importable; otherwise returns a no-op tracer so
    local dev and CI never depend on Langfuse being installed or configured.
    """
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        try:
            from langfuse import Langfuse  # pyright: ignore[reportMissingImports]
        except ModuleNotFoundError:
            logger.warning(
                "Langfuse keys are set but the 'langfuse' package is not installed; "
                "tracing will be a no-op. Install the 'observability' extra to enable it."
            )
            return Tracer(NoOpSink())
        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        return Tracer(LangfuseSink(client))
    return Tracer(NoOpSink())


@lru_cache
def get_tracer() -> Tracer:
    """Return the process-wide :class:`Tracer`, built from the global settings."""
    return build_tracer(get_settings())


def traced(name: str | None = None, *, tracer: Tracer | None = None) -> Callable[[F], F]:
    """Wrap a function so each call runs inside a span.

    ``name`` defaults to the function's qualified name. When ``tracer`` is not
    given, the process tracer (:func:`get_tracer`) is resolved lazily at call
    time, so decorating a function never forces tracer construction at import.
    """

    def decorator(func: F) -> F:
        span_name = name or func.__qualname__

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            active = tracer or get_tracer()
            with active.span(span_name):
                return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
