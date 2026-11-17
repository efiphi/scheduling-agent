"""Busy times from calendar events (calendar.py): invariant 5, T26."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from google_gateway.calendar import (
    EVENT_FIELDS,
    CalendarEvent,
    GoogleCalendarReader,
    busy_intervals,
    is_busy,
)
from shared.messages import Interval

TZ = ZoneInfo("Asia/Jerusalem")
WINDOW = Interval(start=datetime(2026, 11, 3, tzinfo=TZ), end=datetime(2026, 11, 4, tzinfo=TZ))


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 3, hour, minute, tzinfo=TZ)


def event(start: int, end: int, **changes: Any) -> CalendarEvent:
    values: dict[str, Any] = {
        "start": at(start),
        "end": at(end),
        "cancelled": False,
        "transparent": False,
        "organised_by_user": True,
        "user_response": None,
    }
    values.update(changes)
    return CalendarEvent(**values)


@pytest.mark.parametrize(
    ("changes", "busy"),
    [
        ({}, True),  # the user's own event
        ({"organised_by_user": False, "user_response": "accepted"}, True),
        ({"organised_by_user": False, "user_response": "tentative"}, True),
        ({"organised_by_user": False, "user_response": "needsAction"}, False),
        ({"organised_by_user": False, "user_response": "declined"}, False),
        ({"cancelled": True}, False),
        ({"transparent": True}, False),  # marked "free"
    ],
)
def test_which_events_count_as_busy(changes: dict[str, Any], busy: bool) -> None:
    assert is_busy(event(10, 11, **changes)) is busy


def test_t26_a_flood_of_unanswered_invitations_blocks_nothing() -> None:
    invites = [
        event(h, h + 1, organised_by_user=False, user_response="needsAction") for h in range(9, 18)
    ]
    assert busy_intervals(invites, WINDOW) == ()


def test_overlapping_and_touching_events_merge_into_one_interval() -> None:
    events = [event(9, 10), event(10, 11), event(10, 12), event(14, 15)]
    assert busy_intervals(events, WINDOW) == (
        Interval(start=at(9), end=at(12)),
        Interval(start=at(14), end=at(15)),
    )


def test_events_are_clipped_to_the_window() -> None:
    spanning = CalendarEvent(
        start=datetime(2026, 11, 2, 22, tzinfo=TZ),
        end=at(1),
        cancelled=False,
        transparent=False,
        organised_by_user=True,
        user_response=None,
    )
    assert busy_intervals([spanning], WINDOW) == (Interval(start=WINDOW.start, end=at(1)),)


def test_invariant_5_google_is_asked_for_times_only() -> None:
    for never in ("summary", "description", "location", "email", "displayName", "hangoutLink"):
        assert never not in EVENT_FIELDS


class FakeEventsApi:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.kwargs: dict[str, Any] = {}

    def list(self, **kwargs: Any) -> "FakeEventsApi":
        self.kwargs = kwargs
        return self

    def execute(self) -> dict[str, Any]:
        return {"items": self.items}


def test_reader_parses_timed_all_day_and_invited_events(monkeypatch: pytest.MonkeyPatch) -> None:
    items: list[dict[str, Any]] = [
        {
            "start": {"dateTime": "2026-11-03T10:00:00+02:00"},
            "end": {"dateTime": "2026-11-03T11:00:00+02:00"},
            "organizer": {"self": True},
        },
        {
            "start": {"date": "2026-11-03"},
            "end": {"date": "2026-11-04"},
            "transparency": "transparent",
        },
        {
            "start": {"dateTime": "2026-11-03T12:00:00+02:00"},
            "end": {"dateTime": "2026-11-03T13:00:00+02:00"},
            "attendees": [{"self": True, "responseStatus": "accepted"}],
        },
    ]
    api = FakeEventsApi(items)
    reader = GoogleCalendarReader.__new__(GoogleCalendarReader)
    reader._events = api
    reader._tz = TZ
    events = reader.events(WINDOW)
    assert api.kwargs["fields"] == EVENT_FIELDS and api.kwargs["singleEvents"] is True
    assert [is_busy(e) for e in events] == [True, False, True]
    assert events[1].start == at(0)
