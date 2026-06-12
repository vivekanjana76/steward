"""Unit tests for observability tracing.

These assert the two contracts that matter for safety and stability:

* the no-op path (no Langfuse keys) makes no network calls and never raises;
* spans capture latency/usage/cost/errors and carry a ``trace_id``, and the
  Langfuse binding is driven entirely through an injected stub (no network).
"""

from __future__ import annotations

from typing import Any

import pytest

from steward.config import Settings
from steward.observability import (
    LangfuseSink,
    NoOpSink,
    SpanRecord,
    Tracer,
    build_tracer,
    new_trace_id,
    traced,
)


class _RecordingSink:
    """A sink that captures finished spans for assertions."""

    def __init__(self) -> None:
        self.records: list[SpanRecord] = []
        self.flushes = 0

    def record(self, record: SpanRecord) -> None:
        self.records.append(record)

    def flush(self) -> None:
        self.flushes += 1


def test_new_trace_id_is_unique_and_opaque() -> None:
    a, b = new_trace_id(), new_trace_id()
    assert a != b
    assert a.isalnum()


def test_span_records_once_with_trace_id_and_metadata() -> None:
    sink = _RecordingSink()
    tracer = Tracer(sink)

    with tracer.span("triage", trace_id="abc123", node="triage") as span:
        span.record_usage(input_tokens=10, output_tokens=4)
        span.record_usage(input_tokens=5)
        span.set_cost(0.0012)
        span.set_metadata(model="claude-sonnet-4-6")

    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.trace_id == "abc123"
    assert rec.name == "triage"
    assert rec.input_tokens == 15
    assert rec.output_tokens == 4
    assert rec.cost_usd == 0.0012
    assert rec.status == "ok"
    assert rec.error is None
    assert rec.latency_ms >= 0.0
    assert rec.metadata == {"node": "triage", "model": "claude-sonnet-4-6"}


def test_span_mints_trace_id_when_absent() -> None:
    sink = _RecordingSink()
    with Tracer(sink).span("work"):
        pass
    assert sink.records[0].trace_id  # non-empty


def test_span_records_error_and_reraises() -> None:
    sink = _RecordingSink()
    tracer = Tracer(sink)

    with pytest.raises(ValueError, match="boom"), tracer.span("reproduce", trace_id="t1"):
        raise ValueError("boom")

    assert len(sink.records) == 1
    rec = sink.records[0]
    assert rec.status == "error"
    assert rec.error is not None
    assert "ValueError" in rec.error
    assert "boom" in rec.error
    assert rec.trace_id == "t1"


def test_flush_delegates_to_sink() -> None:
    sink = _RecordingSink()
    Tracer(sink).flush()
    assert sink.flushes == 1


def test_traced_decorator_wraps_call_in_a_span() -> None:
    sink = _RecordingSink()
    tracer = Tracer(sink)

    @traced("classify", tracer=tracer)
    def classify(x: int) -> int:
        return x * 2

    assert classify(21) == 42
    assert len(sink.records) == 1
    assert sink.records[0].name == "classify"


def test_traced_decorator_records_span_on_exception() -> None:
    sink = _RecordingSink()
    tracer = Tracer(sink)

    @traced(tracer=tracer)
    def explode() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        explode()

    assert len(sink.records) == 1
    assert sink.records[0].status == "error"
    assert sink.records[0].name.endswith("explode")


# --- no-op fallback -------------------------------------------------------


def test_build_tracer_without_keys_is_noop() -> None:
    settings = Settings.model_construct(langfuse_public_key=None, langfuse_secret_key=None)
    tracer = build_tracer(settings)
    assert isinstance(tracer._sink, NoOpSink)


def test_build_tracer_partial_keys_is_noop() -> None:
    settings = Settings.model_construct(langfuse_public_key="pk-only", langfuse_secret_key=None)
    assert isinstance(build_tracer(settings)._sink, NoOpSink)


def test_noop_path_makes_no_calls_and_never_raises() -> None:
    settings = Settings.model_construct(langfuse_public_key=None, langfuse_secret_key=None)
    tracer = build_tracer(settings)

    # Exercising the full span lifecycle on the no-op tracer must be inert.
    with tracer.span("x") as span:
        span.record_usage(input_tokens=1, output_tokens=1)
        span.set_cost(1.0)
    tracer.flush()


def test_build_tracer_falls_back_when_langfuse_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keys present but the package not importable → no-op, not a crash."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "langfuse":
            raise ModuleNotFoundError("No module named 'langfuse'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    settings = Settings.model_construct(
        langfuse_public_key="pk", langfuse_secret_key="sk", langfuse_host=None
    )
    assert isinstance(build_tracer(settings)._sink, NoOpSink)


# --- Langfuse binding (stub, no network) ----------------------------------


class _StubTrace:
    def __init__(self) -> None:
        self.span_calls: list[dict[str, Any]] = []

    def span(self, **kwargs: Any) -> None:
        self.span_calls.append(kwargs)


class _StubLangfuse:
    def __init__(self) -> None:
        self.trace_calls: list[dict[str, Any]] = []
        self.flushes = 0
        self.last_trace = _StubTrace()

    def trace(self, **kwargs: Any) -> _StubTrace:
        self.trace_calls.append(kwargs)
        self.last_trace = _StubTrace()
        return self.last_trace

    def flush(self) -> None:
        self.flushes += 1


def test_langfuse_sink_translates_record_to_client_calls() -> None:
    client = _StubLangfuse()
    tracer = Tracer(LangfuseSink(client))

    with tracer.span("patch", trace_id="trace-1") as span:
        span.record_usage(input_tokens=100, output_tokens=20)
        span.set_cost(0.05)
    tracer.flush()

    assert client.trace_calls[0]["id"] == "trace-1"
    assert client.trace_calls[0]["name"] == "patch"
    span_call = client.last_trace.span_calls[0]
    assert span_call["name"] == "patch"
    assert span_call["usage"] == {"input": 100, "output": 20, "total_cost": 0.05}
    assert span_call["metadata"]["status"] == "ok"
    assert client.flushes == 1


def test_langfuse_sink_swallows_backend_errors() -> None:
    class _Boom:
        def trace(self, **kwargs: Any) -> Any:
            raise RuntimeError("backend down")

        def flush(self) -> None:
            raise RuntimeError("flush failed")

    tracer = Tracer(LangfuseSink(_Boom()))
    # A failing backend must not break the traced work or flush.
    with tracer.span("work"):
        pass
    tracer.flush()
