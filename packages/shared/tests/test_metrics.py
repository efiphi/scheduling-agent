"""shared.metrics: the readings behind the gauges (E13, T24)."""

from typing import Any

from shared import metrics


class FakeRedis:
    def __init__(self, groups: list[dict[str, Any]]) -> None:
        self.groups = groups

    def xinfo_groups(self, stream: str) -> list[dict[str, Any]]:
        return self.groups


def test_e13_backlog_counts_waiting_and_unacknowledged_messages() -> None:
    redis = FakeRedis(
        [{"name": b"other", "lag": 9, "pending": 9}, {"name": b"agent", "lag": 3, "pending": 2}]
    )
    assert metrics.stream_backlog(redis, "agent:email-tasks", "agent") == [
        (5.0, {"stream": "agent:email-tasks"})
    ]


def test_a_group_that_does_not_exist_yet_reports_nothing() -> None:
    assert metrics.stream_backlog(FakeRedis([]), "s", "g") == []


def test_redis_returning_no_lag_counts_as_zero() -> None:
    # Redis reports lag as nil when it cannot compute it.
    redis = FakeRedis([{"name": "g", "lag": None, "pending": 4}])
    assert metrics.stream_backlog(redis, "s", "g") == [(4.0, {"stream": "s"})]


def test_a_failing_reading_is_skipped_not_raised() -> None:
    def broken() -> list[metrics.Reading]:
        raise ConnectionError("redis is down")

    assert metrics.observations(broken) == []
    [one] = metrics.observations(lambda: [(1.5, {"stream": "s"})])
    assert one.value == 1.5 and one.attributes == {"stream": "s"}
