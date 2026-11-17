"""Security events become a counter and a log line, with no personal data (ADR-022, T22)."""

import logging
from uuid import UUID

import pytest

from shared import security


def test_a_listed_kind_is_counted_and_logged_by_name(caplog: pytest.LogCaptureFixture) -> None:
    user = UUID("00000000-0000-0000-0000-000000000001")
    with caplog.at_level(logging.WARNING, logger="security"):
        security.record("stop_code_failed", user)
    assert caplog.messages == [f"security event: kind=stop_code_failed user_id={user}"]


def test_t22_an_unlisted_kind_cannot_add_a_series(caplog: pytest.LogCaptureFixture) -> None:
    # A typo, or a kind built from input, must not create a new metric series per value.
    with caplog.at_level(logging.WARNING, logger="security"):
        security.record("attacker@example.org")
    assert caplog.messages == ["security event: kind=unlisted user_id=-"]


def test_e13_every_kind_starts_at_zero_so_the_first_burst_counts() -> None:
    # A series that first appears at 6 shows no increase() in Prometheus, so rules miss it.
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    counter = provider.get_meter("test").create_counter("sa.security.events")
    original = security.SECURITY_EVENTS
    security.SECURITY_EVENTS = counter
    try:
        security.prime()
    finally:
        security.SECURITY_EVENTS = original
    data = reader.get_metrics_data()
    assert data is not None
    points = [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
    ]
    kinds = {dict(point.attributes or {})["kind"] for point in points}
    assert kinds == {*security.KINDS, security.UNLISTED}
    assert all(getattr(point, "value", None) == 0 for point in points)
