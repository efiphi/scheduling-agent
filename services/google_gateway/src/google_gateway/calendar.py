"""Reading busy times from Google Calendar (ADR-010, invariant 5, T26).

Free/busy is computed from the user's own events, not from Google's freeBusy endpoint:
that endpoint needs another scope, and it counts every invitation as busy, so anyone could
fill the calendar with invites and leave no free slot (T26).

Invariant 5 starts at the API call: the request asks Google only for each event's times,
status, transparency and whether the user organised or accepted it. Titles, descriptions,
locations and other attendees' addresses are never fetched, so they cannot leak further.

An event counts as busy when:
- it is not cancelled and not marked "free" (transparency "transparent"), and
- the user organised it, or accepted it (or said "maybe"). An invitation the user has not
  answered, or declined, is not busy (T26).
All-day events count only if marked busy, which Google does not do by default.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from shared.messages import Interval

# Only what the busy rule needs. `attendees(self,responseStatus)` returns the user's own
# answer without anyone's address.
EVENT_FIELDS = (
    "items(status,transparency,start,end,organizer/self,attendees(self,responseStatus)),"
    "nextPageToken"
)
BUSY_RESPONSES = {"accepted", "tentative"}


@dataclass(frozen=True)
class CalendarEvent:
    start: datetime
    end: datetime
    cancelled: bool
    transparent: bool
    organised_by_user: bool
    user_response: str | None  # accepted / tentative / declined / needsAction / None


class CalendarReader(Protocol):
    def events(self, window: Interval) -> list[CalendarEvent]: ...


class GoogleCalendarReader:
    def __init__(self, credentials: Any, time_zone: str) -> None:
        self._events = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        ).events()
        self._tz = ZoneInfo(time_zone)

    def events(self, window: Interval) -> list[CalendarEvent]:
        found: list[CalendarEvent] = []
        token: str | None = None
        while True:
            page = self._events.list(
                calendarId="primary",
                timeMin=window.start.isoformat(),
                timeMax=window.end.isoformat(),
                singleEvents=True,  # expand recurring events into their occurrences
                fields=EVENT_FIELDS,
                pageToken=token,
                maxResults=250,
            ).execute()
            found.extend(self._parse(item) for item in page.get("items", []))
            token = page.get("nextPageToken")
            if not token:
                return found

    def _parse(self, item: dict[str, Any]) -> CalendarEvent:
        own = next((a for a in item.get("attendees", []) if a.get("self")), None)
        return CalendarEvent(
            start=self._when(item["start"]),
            end=self._when(item["end"]),
            cancelled=item.get("status") == "cancelled",
            transparent=item.get("transparency") == "transparent",
            organised_by_user=bool(item.get("organizer", {}).get("self")),
            user_response=own.get("responseStatus") if own else None,
        )

    def _when(self, value: dict[str, str]) -> datetime:
        if "dateTime" in value:
            return datetime.fromisoformat(value["dateTime"])
        # All-day: a date, starting at midnight in the user's time zone.
        return datetime.combine(date.fromisoformat(value["date"]), time(0), self._tz)


def is_busy(event: CalendarEvent) -> bool:
    if event.cancelled or event.transparent:
        return False
    return event.organised_by_user or event.user_response in BUSY_RESPONSES


def busy_intervals(events: Sequence[CalendarEvent], window: Interval) -> tuple[Interval, ...]:
    """Busy times inside the window, merged where they touch or overlap. Times only."""
    spans = sorted(
        (max(e.start, window.start), min(e.end, window.end))
        for e in events
        if is_busy(e) and e.end > window.start and e.start < window.end
    )
    merged: list[tuple[datetime, datetime]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        elif end > start:
            merged.append((start, end))
    return tuple(Interval(start=s, end=e) for s, e in merged)
