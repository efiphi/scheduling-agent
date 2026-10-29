"""Slot choice in code (slots.py): work hours, buffers, busy times, spread (invariant 5)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from agent_fakes import CONTEXT, request

from agent.slots import pick_slots, search_window
from shared.messages import Interval

TZ = ZoneInfo("Asia/Jerusalem")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def test_one_slot_per_day_first_at_the_start_of_work() -> None:
    slots = pick_slots(request(), CONTEXT, busy=())
    assert [s.start for s in slots] == [at(3, 9), at(4, 9), at(5, 9)]
    assert all(s.end - s.start == timedelta(minutes=30) for s in slots)


def test_busy_time_and_its_buffer_are_avoided() -> None:
    busy = (Interval(start=at(3, 9), end=at(3, 10)),)
    slots = pick_slots(request(earliest=date(2026, 11, 3), latest=date(2026, 11, 3)), CONTEXT, busy)
    # 10:00 is inside the 15-minute buffer; 10:30 is the first clean start.
    assert slots[0].start == at(3, 10, 30)


def test_a_single_day_gets_up_to_three_slots_spread_out() -> None:
    one_day = request(earliest=date(2026, 11, 3), latest=date(2026, 11, 3))
    starts = [s.start for s in pick_slots(one_day, CONTEXT, busy=())]
    assert starts == [at(3, 9), at(3, 11), at(3, 13)]


def test_weekend_days_are_skipped() -> None:
    # Friday 6 and Saturday 7 November are not work days; Sunday 8 is.
    weekend = request(earliest=date(2026, 11, 6), latest=date(2026, 11, 8))
    assert {s.start.date() for s in pick_slots(weekend, CONTEXT, busy=())} == {date(2026, 11, 8)}


def test_part_of_day_is_respected() -> None:
    afternoon = request(time_of_day="afternoon")
    assert all(12 <= s.start.hour < 16 for s in pick_slots(afternoon, CONTEXT, busy=()))
    evening = request(time_of_day="evening")
    # Evening is clipped to work hours (until 18:00).
    assert all(
        s.start.hour >= 16 and s.end <= s.start.replace(hour=18)
        for s in pick_slots(evening, CONTEXT, busy=())
    )


def test_nothing_sooner_than_an_hour_from_now() -> None:
    today = request(earliest=date(2026, 11, 2), latest=date(2026, 11, 2))
    # Now is 09:00 on 2 November.
    assert pick_slots(today, CONTEXT, busy=())[0].start == at(2, 10)


def test_a_fully_busy_range_gives_no_slots() -> None:
    busy = (Interval(start=at(3, 0), end=at(6, 0)),)
    assert pick_slots(request(), CONTEXT, busy) == ()


def test_slots_never_cross_the_end_of_the_working_day() -> None:
    long_meeting = request(
        duration_minutes=120, earliest=date(2026, 11, 3), latest=date(2026, 11, 3)
    )
    busy = (Interval(start=at(3, 9), end=at(3, 16)),)
    assert pick_slots(long_meeting, CONTEXT, busy) == ()


def test_search_window_covers_whole_local_days() -> None:
    window = search_window(request(), CONTEXT)
    assert (window.start, window.end) == (at(3, 0), at(6, 0))
