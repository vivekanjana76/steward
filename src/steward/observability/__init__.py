"""Observability for Steward: tracing of every node and tool call.

The public surface is intentionally small:

* :func:`get_tracer` / :func:`build_tracer` — obtain the process tracer, which
  is backed by Langfuse when keys are configured and degrades to a no-op
  otherwise (CLAUDE.md §11).
* :class:`Tracer` — its :meth:`~Tracer.span` context manager and the
  :func:`traced` decorator wrap a unit of work, capturing latency, token usage,
  cost, and a ``trace_id`` for the audit log.

Importing this package is side-effect free: no Langfuse client is constructed
and no environment is read until a tracer is built.
"""

from __future__ import annotations

from steward.observability.tracing import (
    LangfuseSink,
    NoOpSink,
    Span,
    SpanRecord,
    SpanSink,
    Tracer,
    build_tracer,
    get_tracer,
    new_trace_id,
    traced,
)

__all__ = [
    "LangfuseSink",
    "NoOpSink",
    "Span",
    "SpanRecord",
    "SpanSink",
    "Tracer",
    "build_tracer",
    "get_tracer",
    "new_trace_id",
    "traced",
]
