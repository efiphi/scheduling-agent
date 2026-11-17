"""shared.tracing: one email is one trace, and context from outside is not trusted."""

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from shared import tracing

_EXPORTER = InMemorySpanExporter()


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    provider = tracing.configure("test-service")
    if not getattr(provider, "_test_exporter", False):
        provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
        provider._test_exporter = True  # type: ignore[attr-defined]
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()


def test_a_message_carries_its_trace_to_the_consumer(spans: InMemorySpanExporter) -> None:
    tracer = tracing.tracer("test")
    with tracer.start_as_current_span("email.received", context=tracing.new_trace()) as first:
        fields = tracing.inject({"task": "{}"})
    # As Redis returns them: bytes keys and values.
    received = {k.encode(): v.encode() for k, v in fields.items()}
    with tracer.start_as_current_span("agent.task", context=tracing.extract(received)) as second:
        pass
    assert second.get_span_context().trace_id == first.get_span_context().trace_id
    assert set(fields) == {"task", "traceparent"}


def test_a_stored_traceparent_continues_the_trace(spans: InMemorySpanExporter) -> None:
    tracer = tracing.tracer("test")
    with tracer.start_as_current_span("plan.handle", context=tracing.new_trace()) as created:
        stored = tracing.traceparent()
    # Later, in another process: the executor continues from the database row.
    ctx = tracing.from_traceparent(stored)
    with tracer.start_as_current_span("action.execute", context=ctx) as executed:
        pass
    assert executed.get_span_context().trace_id == created.get_span_context().trace_id


@pytest.mark.parametrize(
    "fields",
    [None, {}, {b"traceparent": b"not-a-traceparent"}, {"traceparent": 42}, {b"x": b"y"}],
)
def test_a_missing_or_malformed_context_starts_a_new_trace(
    spans: InMemorySpanExporter, fields: dict[object, object] | None
) -> None:
    with tracing.tracer("test").start_as_current_span("x", context=tracing.extract(fields)):
        parent = trace.get_current_span().parent  # type: ignore[attr-defined]
    assert parent is None


def test_spans_are_not_given_context_by_http_headers(spans: InMemorySpanExporter) -> None:
    # The global propagator ignores incoming headers: a browser or Meta's webhook cannot pick
    # the trace our spans join.
    from opentelemetry.propagate import extract

    header = "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01"
    ctx = extract({"traceparent": header})
    assert not trace.get_current_span(ctx).get_span_context().is_valid
