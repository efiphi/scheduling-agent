"""The pending action's hash and expiry (pending_action.py): invariant 4, T3, E7."""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from google_gateway.pending_action import content_hash, expires_at
from shared.messages import AgentContext

TZ = ZoneInfo("Asia/Jerusalem")


def context(now: datetime) -> AgentContext:
    return AgentContext(
        time_zone="Asia/Jerusalem",
        now=now,
        work_days=(0, 1, 2, 3, 4),
        work_start=time(9),
        work_end=time(18),
        default_duration_minutes=30,
        buffer_minutes=15,
    )


def test_t3_any_change_to_the_content_changes_the_hash() -> None:
    payload = {"to": ["dana@example.org"], "body": "Hi", "slots": [{"start": "a"}]}
    original = content_hash(payload)
    assert content_hash(dict(reversed(list(payload.items())))) == original  # key order: same
    for changed in (
        {**payload, "to": ["dana@example.org", "attacker@example.org"]},
        {**payload, "body": "Hi."},
        {**payload, "slots": [{"start": "b"}]},
    ):
        assert content_hash(changed) != original
    assert original.startswith("sha256:") and len(original) == 7 + 64


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # Monday 09:00 -> Monday 18:00.
        (datetime(2026, 11, 2, 9, tzinfo=TZ), datetime(2026, 11, 2, 18, tzinfo=TZ)),
        # Monday 19:00, after work -> Tuesday 18:00.
        (datetime(2026, 11, 2, 19, tzinfo=TZ), datetime(2026, 11, 3, 18, tzinfo=TZ)),
        # Thursday 20:00 -> Sunday 18:00 (Friday and Saturday are not work days).
        (datetime(2026, 11, 5, 20, tzinfo=TZ), datetime(2026, 11, 8, 18, tzinfo=TZ)),
    ],
)
def test_e7_expires_at_the_end_of_the_nearest_workday_not_yet_over(
    now: datetime, expected: datetime
) -> None:
    assert expires_at(context(now.astimezone(UTC)), time(18)) == expected
