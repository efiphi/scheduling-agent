"""Distributed tracing with OpenTelemetry (Layer 3, step 3.3).

    from shared import tracing
    tracing.configure("plan-handler")
    with tracing.tracer(__name__).start_as_current_span("plan.handle", context=...):
        ...

One email is one trace: the poller starts it, and every hop carries it on.
- Redis Streams: `inject()` adds a `traceparent` field to a message, and the consumer's
  `extract()` continues from it.
- The approval, minutes or hours later: the pending action stores its `traceparent`, and the
  executor continues that trace, so the wait for the user shows as a gap, not a new trace.

Spans hold ids, decisions and counts, never email content or secrets (T22), like the logs.

Trace context from outside is not trusted. The HTTP propagator is disabled globally, so a
`traceparent` header from a browser or from Meta's webhook cannot attach our spans to a
trace someone else chose. Only our own Redis messages and database rows carry context, and
those go through `extract()` here.

Without OTEL_EXPORTER_OTLP_ENDPOINT (Compose, tests) spans are created and dropped: the
code path is the same, nothing is sent.
"""

import os
from collections.abc import Mapping
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.textmap import (
    CarrierT,
    Getter,
    Setter,
    TextMapPropagator,
    default_getter,
    default_setter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

TRACEPARENT = "traceparent"
_PROPAGATOR = TraceContextTextMapPropagator()


class _IgnoreIncoming(TextMapPropagator):
    """The global propagator: reads no context from HTTP headers and writes none.

    So a request from outside always starts a new trace (see the module docstring). It
    returns an empty context rather than None: the HTTP instrumentation uses the result as
    the parent, and an empty CompositePropagator would hand it None and crash it.
    """

    def extract(
        self,
        carrier: CarrierT,
        context: otel_context.Context | None = None,
        getter: Getter[CarrierT] = default_getter,
    ) -> otel_context.Context:
        return otel_context.Context()

    def inject(
        self,
        carrier: CarrierT,
        context: otel_context.Context | None = None,
        setter: Setter[CarrierT] = default_setter,
    ) -> None:
        return None

    @property
    def fields(self) -> set[str]:
        return set()


def configure(service: str, exporter: SpanExporter | None = None) -> TracerProvider:
    """Install the tracer provider for this process. `exporter` is for tests."""
    # No context from HTTP headers: see the module docstring.
    set_global_textmap(_IgnoreIncoming())
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        # OpenTelemetry allows one global provider per process; a second configure (tests
        # build many apps) reuses it instead of being silently ignored.
        provider = current
    else:
        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": service, "service.namespace": "scheduling-agent"}
            )
        )
        trace.set_tracer_provider(provider)
    if exporter is None and os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()  # reads the endpoint from the environment
    if exporter is not None:
        # Batches are sent in the background; the provider flushes them at exit, which a
        # CronJob run (gmail-poll) relies on.
        provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def new_trace() -> otel_context.Context:
    """An empty context: a span started in it is the root of a new trace."""
    return otel_context.Context()


def traceparent() -> str | None:
    """The current span as a W3C traceparent string, to store or send."""
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier.get(TRACEPARENT)


def inject(fields: Mapping[str, str]) -> dict[Any, Any]:
    """Stream fields plus the current trace context.

    Typed loosely on the way out: redis-py's xadd takes a dict of its own key and value
    unions, and dict is invariant, so a dict[str, str] would not type-check there.
    """
    value = traceparent()
    return {**fields, TRACEPARENT: value} if value else dict(fields)


def extract(fields: Mapping[Any, Any] | None) -> otel_context.Context:
    """The trace context in stream fields (bytes or str keys) or a stored traceparent row.

    Anything malformed gives an empty context, so a bad value starts a new trace instead
    of failing the message.
    """
    if not fields:
        return new_trace()
    raw = fields.get(TRACEPARENT, fields.get(TRACEPARENT.encode()))
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")
    if not isinstance(raw, str):
        return new_trace()
    return _PROPAGATOR.extract({TRACEPARENT: raw}, context=new_trace())


def from_traceparent(value: str | None) -> otel_context.Context:
    return extract({TRACEPARENT: value} if value else None)


# Paths never traced by the HTTP instrumentation: their query strings carry secrets (the
# OAuth callbacks' code and state, the WhatsApp handshake's verify token, T16, T22), and
# health checks would only be noise. Matched anywhere in the URL, comma-separated.
UNTRACED_PATHS = "healthz,oauth/google/callback,auth/google/callback,whatsapp/webhook"


def instrument_fastapi(app: Any) -> None:
    """A span per HTTP request, except UNTRACED_PATHS. For the api and the gateway only."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls=UNTRACED_PATHS)
