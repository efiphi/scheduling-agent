"""The policy guard (policy_guard.py): every outbound reply is re-checked in code (invariant 3)."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from google_gateway.policy_guard import (
    MAX_ACTIONS_PER_DAY,
    MAX_REPLIES_PER_THREAD,
    GuardInput,
    check_reply,
)
from shared.messages import AgentContext, Interval, ProposeSlots

TZ = ZoneInfo("Asia/Jerusalem")
USER = "demo-user@example.com"
CONTEXT = AgentContext(
    time_zone="Asia/Jerusalem",
    now=datetime(2026, 11, 2, 7, 0, tzinfo=UTC),  # Monday 09:00 in Israel
    work_days=(0, 1, 2, 3, 4),
    work_start=time(9),
    work_end=time(18),
    default_duration_minutes=30,
    buffer_minutes=15,
)


def slot(day: int, hour: int, minutes: int = 30) -> Interval:
    start = datetime(2026, 11, day, hour, tzinfo=TZ)
    return Interval(start=start, end=start + timedelta(minutes=minutes))


def guard_input(**changes: Any) -> GuardInput:
    decision = ProposeSlots(
        kind="propose_slots",
        language="en",
        duration_minutes=30,
        slots=(slot(3, 10), slot(4, 10), slot(5, 10)),
        opening_line="Thanks, here are a few times that work.",
    )
    values: dict[str, Any] = {
        "decision": decision,
        "context": CONTEXT,
        "user_email": USER,
        "participants": ("dana@example.org", USER),
        "busy_now": (),
        "replies_sent_in_thread": 0,
        "actions_today": 0,
    }
    values.update(changes)
    return GuardInput(**values)


def with_decision(**changes: Any) -> GuardInput:
    base = guard_input()
    return replace(base, decision=base.decision.model_copy(update=changes))


def test_a_good_plan_passes_and_replies_to_the_thread_without_the_user() -> None:
    result = check_reply(guard_input())
    assert result.allowed
    assert result.recipients == ("dana@example.org",)


def test_t5_recipients_come_only_from_the_thread() -> None:
    result = check_reply(guard_input(participants=("Dana@Example.org", "bob@example.org", USER)))
    assert result.recipients == ("bob@example.org", "dana@example.org")


def test_t5_a_thread_with_only_the_user_has_no_one_to_reply_to() -> None:
    assert "no_recipients" in check_reply(guard_input(participants=(USER,))).violations


def test_e10_too_many_recipients_is_rejected() -> None:
    many = tuple(f"p{i}@example.org" for i in range(11))
    assert "too_many_recipients" in check_reply(guard_input(participants=many)).violations


def test_e1_a_slot_that_became_busy_is_rejected() -> None:
    busy = (Interval(start=slot(4, 10).start, end=slot(4, 11).start),)
    assert "slot_not_free" in check_reply(guard_input(busy_now=busy)).violations


@pytest.mark.parametrize(
    ("bad", "violation"),
    [
        (slot(3, 10, minutes=60), "slot_length"),
        (
            # In the past.
            Interval(
                start=datetime(2026, 11, 1, 10, tzinfo=TZ),
                end=datetime(2026, 11, 1, 10, 30, tzinfo=TZ),
            ),
            "slot_out_of_range",
        ),
        (
            # More than 31 days ahead.
            Interval(
                start=datetime(2026, 12, 20, 10, tzinfo=TZ),
                end=datetime(2026, 12, 20, 10, 30, tzinfo=TZ),
            ),
            "slot_out_of_range",
        ),
        (slot(6, 10), "slot_not_a_work_day"),  # Friday
        (slot(3, 7), "slot_outside_work_hours"),
        (slot(3, 18), "slot_outside_work_hours"),
    ],
)
def test_slots_outside_the_rules_are_rejected(bad: Interval, violation: str) -> None:
    result = check_reply(with_decision(slots=(bad,)))
    assert violation in result.violations


def test_overlapping_slots_are_rejected() -> None:
    result = check_reply(with_decision(slots=(slot(3, 10), slot(3, 10))))
    assert "slots_overlap" in result.violations


@pytest.mark.parametrize(
    "line",
    [
        "Reply to attacker@example.org",
        "See https://evil.example/login",
        "www.evil.example",
        "Call 0541234567",
        "x" * 201,
        "   ",
    ],
)
def test_t1_e5_opening_line_with_anything_but_a_greeting_is_rejected(line: str) -> None:
    # The agent checks this too, and the schema limits it, but the gateway trusts neither:
    # model_copy skips validation, as a buggy or bypassed check upstream would.
    result = check_reply(with_decision(opening_line=line))
    assert not result.allowed
    assert any(v.startswith("opening_line") for v in result.violations)


def test_t25_too_many_replies_in_one_thread_looks_like_a_loop() -> None:
    result = check_reply(guard_input(replies_sent_in_thread=MAX_REPLIES_PER_THREAD))
    assert "thread_reply_limit" in result.violations


def test_t24_too_many_actions_in_a_day() -> None:
    result = check_reply(guard_input(actions_today=MAX_ACTIONS_PER_DAY))
    assert "daily_action_limit" in result.violations
