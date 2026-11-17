"""Creating the approved event with a Meet link (UC-M2, calendar.events.owned scope).

Idempotent (E8): the event id and the Meet request id are both derived from the action's
idempotency key. Creating the same event twice makes Google answer 409, which means it
is already there, so a retry after a crash never creates a second event or a second
Meet link. Title and description come from code (pending_action.event_payload).
Google emails the invitation to the attendees (sendUpdates=all).
"""

from typing import Any, Protocol
from uuid import UUID

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def event_id(idempotency_key: UUID) -> str:
    # Google allows lowercase a-v and 0-9; a UUID's hex digits are a subset.
    return idempotency_key.hex


class CalendarWriter(Protocol):
    def create_event(self, idempotency_key: UUID, payload: dict[str, Any]) -> str:
        """The event id; the existing one if this key already created it."""
        ...


class GoogleCalendarWriter:
    def __init__(self, credentials: Any) -> None:
        self._events = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        ).events()

    def create_event(self, idempotency_key: UUID, payload: dict[str, Any]) -> str:
        slot = payload["slots"][0]
        body = {
            "id": event_id(idempotency_key),
            "summary": payload["subject"],
            "description": payload["body"],
            "start": {"dateTime": slot["start"], "timeZone": payload["time_zone"]},
            "end": {"dateTime": slot["end"], "timeZone": payload["time_zone"]},
            "attendees": [{"email": address} for address in payload["to"]],
            "conferenceData": {
                "createRequest": {
                    "requestId": str(idempotency_key),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        try:
            created = self._events.insert(
                calendarId="primary", body=body, conferenceDataVersion=1, sendUpdates="all"
            ).execute()
        except HttpError as error:
            if error.resp.status == 409:  # already created by an earlier attempt
                return event_id(idempotency_key)
            raise
        return str(created["id"])
