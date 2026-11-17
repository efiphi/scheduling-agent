"""Choosing up to three slots to offer: plain code, no model (ADR-002, ADR-012).

The model said what was asked (extraction.py); which times are offered is decided here,
from the user's settings and the busy intervals the gateway returned (invariant 5: busy
times only, no titles or attendees). Rules:
- only the user's work days and hours, and the part of the day that was asked for;
- the user's buffer before and after every busy interval;
- nothing sooner than an hour from now;
- spread out: the first free slot of different days before a second slot on one day.
"""

from collections.abc import Iterator, Sequence
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from agent.extraction import MeetingRequest
from shared.messages import MAX_FREE_BUSY_WINDOW, AgentContext, Interval

MAX_SLOTS = 3
STEP = timedelta(minutes=30)
MIN_LEAD = timedelta(hours=1)
SPREAD = timedelta(hours=2)
# Parts of the day, intersected with the user's working hours.
PARTS = {
    "any": (time(0), time(23, 59)),
    "morning": (time(0), time(12)),
    "afternoon": (time(12), time(16)),
    "evening": (time(16), time(23, 59)),
}


def search_window(request: MeetingRequest, context: AgentContext) -> Interval:
    """The free/busy range to ask the gateway for: the requested days, whole, in local time."""
    tz = ZoneInfo(context.time_zone)
    start = datetime.combine(request.earliest, time(0), tz)
    end = datetime.combine(request.latest + timedelta(days=1), time(0), tz)
    return Interval(start=start, end=min(end, start + MAX_FREE_BUSY_WINDOW))


def pick_slots(
    request: MeetingRequest, context: AgentContext, busy: Sequence[Interval]
) -> tuple[Interval, ...]:
    tz = ZoneInfo(context.time_zone)
    length = timedelta(minutes=request.duration_minutes)
    buffer = timedelta(minutes=context.buffer_minutes)
    earliest_start = context.now + MIN_LEAD
    blocked = [(b.start - buffer, b.end + buffer) for b in busy]

    per_day: list[list[Interval]] = []
    for day in _days(request.earliest, request.latest):
        if _sunday_based(day) not in context.work_days:
            continue
        free = [
            Interval(start=start, end=start + length)
            for start in _starts(day, request, context, tz, length)
            if start >= earliest_start
            and not any(start < b_end and start + length > b_start for b_start, b_end in blocked)
        ]
        if free:
            per_day.append(free)

    # First the earliest free slot of each day; if there are fewer than three days, more
    # slots from the same days, at least SPREAD after the last one chosen on that day.
    chosen: list[Interval] = [free[0] for free in per_day[:MAX_SLOTS]]
    for free in per_day:
        last = free[0].start
        for slot in free[1:]:
            if len(chosen) == MAX_SLOTS:
                break
            if slot.start - last >= SPREAD:
                chosen.append(slot)
                last = slot.start
    return tuple(sorted(chosen, key=lambda s: s.start))


def _days(first: date, last: date) -> Iterator[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def _sunday_based(day: date) -> int:
    # Settings use 0 = Sunday (docs/01-use-cases.md); Python's weekday() has 0 = Monday.
    return (day.weekday() + 1) % 7


def _starts(
    day: date, request: MeetingRequest, context: AgentContext, tz: ZoneInfo, length: timedelta
) -> Iterator[datetime]:
    part_start, part_end = PARTS[request.time_of_day]
    open_at = datetime.combine(day, max(context.work_start, part_start), tz)
    close_at = datetime.combine(day, min(context.work_end, part_end), tz)
    start = open_at
    while start + length <= close_at:
        yield start
        start += STEP
