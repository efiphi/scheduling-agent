"""The free/busy responder's decisions (free_busy_responder.py), with fakes."""

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from google.auth.exceptions import RefreshError
from mail_fakes import FakeCoordination, FakeMailStore
from redis import Redis
from test_calendar import event

from google_gateway.calendar import CalendarEvent
from google_gateway.free_busy_responder import FreeBusyResponder
from google_gateway.token_crypto import EncryptedToken
from shared.messages import FreeBusyRequest, Interval

TZ = ZoneInfo("Asia/Jerusalem")
WINDOW = Interval(start=datetime(2026, 11, 3, tzinfo=TZ), end=datetime(2026, 11, 4, tzinfo=TZ))


class FakeCalendar:
    def __init__(self, events: list[CalendarEvent] | Exception) -> None:
        self.result = events

    def events(self, window: Interval) -> list[CalendarEvent]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def setup(
    calendar: FakeCalendar,
) -> tuple[FreeBusyResponder, FakeMailStore, FakeCoordination, UUID, UUID]:
    store, coordination = FakeMailStore(), FakeCoordination()
    user = store.add_user()
    task_id = uuid4()
    from mail_fakes import NOW

    from shared.messages import EmailTask, UntrustedEmail, UntrustedText

    coordination.enqueue(
        EmailTask(
            task_id=task_id,
            user_id=user,
            thread_id=uuid4(),
            email=UntrustedEmail(
                gmail_message_id="m",
                sender="d@example.org",
                subject=UntrustedText("s"),
                body_text=UntrustedText("b"),
                received_at=NOW,
            ),
            context=store.agent_context(user, NOW),
        )
    )

    def open_calendar(user_id: UUID, token: EncryptedToken, time_zone: str) -> FakeCalendar:
        return calendar

    responder = FreeBusyResponder(
        redis=cast(Redis, None), store=store, coordination=coordination, open_calendar=open_calendar
    )
    return responder, store, coordination, user, task_id


def request(user: UUID, task_id: UUID) -> FreeBusyRequest:
    return FreeBusyRequest(request_id=uuid4(), task_id=task_id, user_id=user, window=WINDOW)


def test_busy_times_only_for_a_task_we_issued() -> None:
    responder, _, _, user, task_id = setup(FakeCalendar([event(10, 11)]))
    reply = responder.answer(request(user, task_id))
    assert reply.status == "ok" and len(reply.busy) == 1


def test_t13_the_agent_cannot_ask_about_another_users_calendar() -> None:
    responder, store, _, _, task_id = setup(FakeCalendar([event(10, 11)]))
    other = store.add_user()
    reply = responder.answer(request(other, task_id))
    assert reply.status == "unavailable" and reply.busy == ()
    assert (other, "free_busy_task_mismatch") in store.security_events


def test_an_invented_task_id_gets_nothing() -> None:
    responder, _, _, user, _ = setup(FakeCalendar([event(10, 11)]))
    assert responder.answer(request(user, uuid4())).status == "unavailable"


def test_e13_rejected_token_marks_the_connection_expired() -> None:
    responder, store, _, user, task_id = setup(FakeCalendar(RefreshError("invalid_grant")))  # type: ignore[no-untyped-call]
    assert responder.answer(request(user, task_id)).status == "unavailable"
    assert user in store.expired


@pytest.mark.parametrize("error", [RuntimeError("boom"), TimeoutError()])
def test_e1_a_failed_calendar_read_is_unavailable_never_free(error: Exception) -> None:
    responder, _, _, user, task_id = setup(FakeCalendar(error))
    reply = responder.answer(request(user, task_id))
    assert reply.status == "unavailable"
