"""Metrics with OpenTelemetry (Layer 3, step 3.5): pushed over OTLP to Alloy, which writes
them to Prometheus. No service opens a /metrics port.

    from shared import metrics
    metrics.configure("plan-handler")
    metrics.ACTIONS_CREATED.add(1, {"kind": "reply_with_slots"})

Every instrument is defined here, so names and attributes stay consistent across services
and a dashboard can rely on them. Attributes are low-cardinality on purpose: outcomes,
kinds, channels, never a user id, an email address or anything from an email (T22). Ids
belong in traces and logs, where one request is looked at; metrics are counted across all.

In Prometheus the names become e.g. `sa_emails_received_total`, `sa_llm_cost_usd_total`.

Without OTEL_EXPORTER_OTLP_ENDPOINT (Compose, tests) the instruments work and record
nothing.
"""

import os
from collections.abc import Callable, Iterable

from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

EXPORT_INTERVAL_MS = 15_000

_meter = otel_metrics.get_meter("scheduling-agent")

# --- Business: what happens to email and actions -----------------------------------------
EMAILS_RECEIVED = _meter.create_counter(
    "sa.emails.received", description="New emails seen by the poller, by filter outcome"
)
AGENT_DECISIONS = _meter.create_counter(
    "sa.agent.decisions", description="Agent plans, by decision kind"
)
ACTIONS_CREATED = _meter.create_counter(
    "sa.actions.created", description="Pending actions created after the policy guard"
)
ACTIONS_DECIDED = _meter.create_counter(
    "sa.actions.decided",
    description="User decisions on pending actions, by result (approved, rejected, expired, ...)",
)
ACTIONS_EXECUTED = _meter.create_counter(
    "sa.actions.executed", description="Executor outcomes for approved actions"
)
APPROVAL_WAIT = _meter.create_histogram(
    "sa.actions.approval_wait",
    unit="s",
    description="From a pending action's creation to its execution: how long the user took",
)

# --- The agent and the model -----------------------------------------------------------------
AGENT_TASK_DURATION = _meter.create_histogram(
    "sa.agent.task.duration", unit="s", description="One email through the agent graph"
)
LLM_TOKENS = _meter.create_counter(
    "sa.llm.tokens", unit="{token}", description="Model tokens, by direction"
)
LLM_COST = _meter.create_counter(
    "sa.llm.cost_usd", description="Model spend in US dollars, from token counts (T24)"
)


def configure(service: str, reader: MetricReader | None = None) -> MeterProvider:
    """Install the meter provider for this process. `reader` is for tests."""
    current = otel_metrics.get_meter_provider()
    if isinstance(current, MeterProvider):
        return current  # one per process, like tracing.configure
    readers: list[MetricReader] = []
    if reader is not None:
        readers.append(reader)
    elif os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        # Sent every 15 s, and once more at exit, which a CronJob run relies on.
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(), export_interval_millis=EXPORT_INTERVAL_MS
            )
        )
    provider = MeterProvider(
        resource=Resource.create(
            {"service.name": service, "service.namespace": "scheduling-agent"}
        ),
        metric_readers=readers,
    )
    otel_metrics.set_meter_provider(provider)
    return provider


# The only attribute keys a metric may carry: low-cardinality, never personal data (T22).
# tests/test_repo.py checks every recording in the code against this list.
ALLOWED_ATTRIBUTES = frozenset(
    {"outcome", "decision", "kind", "result", "channel", "direction", "model", "stream"}
)

Reading = tuple[float, dict[str, str]]


def observations(read: Callable[[], Iterable[Reading]]) -> list[Observation]:
    """Readings as observations; an error skips this reading instead of breaking the export."""
    try:
        return [Observation(value, attributes) for value, attributes in read()]
    except Exception:
        return []


def observe(name: str, description: str, read: Callable[[], Iterable[Reading]]) -> None:
    """A gauge read when metrics are exported, e.g. a queue's backlog or today's spend."""

    def callback(_options: CallbackOptions) -> Iterable[Observation]:
        return observations(read)

    _meter.create_observable_gauge(name, callbacks=[callback], description=description)


def stream_backlog(redis: object, stream: str, group: str) -> list[Reading]:
    """How far a consumer group is behind on its stream: entries not yet delivered (lag) plus
    delivered but not yet acknowledged (pending). A growing number means a stuck consumer,
    the kind of silent failure E13 is about. `redis` is a redis-py client."""
    for info in redis.xinfo_groups(stream):  # type: ignore[attr-defined]
        if info["name"] in (group, group.encode()):
            backlog = (info.get("lag") or 0) + (info.get("pending") or 0)
            return [(float(backlog), {"stream": stream})]
    return []


def observe_stream_backlog(redis: object, stream: str, group: str) -> None:
    observe(
        "sa.queue.backlog",
        "Messages waiting or in progress, per stream",
        lambda: stream_backlog(redis, stream, group),
    )
