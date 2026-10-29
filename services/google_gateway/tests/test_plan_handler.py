"""Plans into pending actions or questions (plan_handler.py), with fakes (T13, E1, E8)."""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from mail_fakes import NOW, FakeCoordination, FakeMailStore
from test_calendar import event
from test_free_busy_responder import FakeCalendar

from google_gateway.actions_store import ThreadInfo
from google_gateway.calendar import CalendarEvent
from google_gateway.plan_handler import GUARD_REJECTED_QUESTION, PlanHandler
from google_gateway.token_crypto import EncryptedToken
from shared.messages import (
    AgentPlan,
    AskUser,
    EmailTask,
    Interval,
    NotAMeetingRequest,
    ProposeSlots,
    UntrustedEmail,
    UntrustedText,
)

TZ = ZoneInfo("Asia/Jerusalem")


@dataclass
class FakeActionStore:
    threads: dict[tuple[UUID, UUID], ThreadInfo] = field(default_factory=dict)
    actions: dict[tuple[UUID, UUID], tuple[dict[str, Any], str, datetime]] = field(
        default_factory=dict
    )
    questions: dict[tuple[UUID, UUID], str] = field(default_factory=dict)
    closed: list[UUID] = field(default_factory=list)
    sent_in_thread: int = 0

    def thread(self, user_id: UUID, thread_id: UUID) -> ThreadInfo | None:
        return self.threads.get((user_id, thread_id))

    def end_of_workday(self, user_id: UUID) -> time:
        return time(18)

    def replies_sent_in_thread(self, user_id: UUID, thread_id: UUID) -> int:
        return self.sent_in_thread

    def actions_since(self, user_id: UUID, since: datetime) -> int:
        return len(self.actions)

    def create_reply_action(
        self,
        user_id: UUID,
        thread_id: UUID,
        task_id: UUID,
        payload: dict[str, Any],
        content_hash: str,
        expires_at: datetime,
    ) -> UUID | None:
        if (user_id, task_id) in self.actions:
            return None
        self.actions[(user_id, task_id)] = (payload, content_hash, expires_at)
        return uuid4()

    def create_question(self, user_id: UUID, thread_id: UUID, task_id: UUID, question: str) -> bool:
        if (user_id, task_id) in self.questions:
            return False
        self.questions[(user_id, task_id)] = question
        return True

    def close_thread(self, user_id: UUID, thread_id: UUID, reason: str) -> None:
        self.closed.append(thread_id)


@dataclass
class Setup:
    handler: PlanHandler
    actions: FakeActionStore
    mail: FakeMailStore
    user: UUID
    thread: UUID
    task: UUID


def make(events: list[CalendarEvent] | Exception | None = None) -> Setup:
    mail, coordination, actions = FakeMailStore(), FakeCoordination(), FakeActionStore()
    user, thread, task = mail.add_user(), uuid4(), uuid4()
    actions.threads[(user, thread)] = ThreadInfo("g-thread", ("dana@example.org",), "open")
    coordination.enqueue(
        EmailTask(
            task_id=task,
            user_id=user,
            thread_id=thread,
            email=UntrustedEmail(
                gmail_message_id="m1",
                sender="dana@example.org",
                subject=UntrustedText("Quick call?"),
                body_text=UntrustedText("b"),
                received_at=NOW,
            ),
            context=mail.agent_context(user, NOW),
        )
    )
    calendar = FakeCalendar([] if events is None else events)

    def open_calendar(user_id: UUID, token: EncryptedToken, time_zone: str) -> FakeCalendar:
        return calendar

    handler = PlanHandler(
        actions=actions,
        mail=mail,
        coordination=coordination,
        open_calendar=open_calendar,
        clock=lambda: NOW,
    )
    return Setup(handler, actions, mail, user, thread, task)


def slot(day: int, hour: int) -> Interval:
    start = datetime(2026, 11, day, hour, tzinfo=TZ)
    return Interval(start=start, end=start + timedelta(minutes=30))


def plan(s: Setup, decision: Any, **changes: Any) -> AgentPlan:
    values: dict[str, Any] = {
        "task_id": s.task,
        "user_id": s.user,
        "thread_id": s.thread,
        "decision": decision,
        "created_at": NOW,
    }
    values.update(changes)
    return AgentPlan(**values)


PROPOSE = ProposeSlots(
    kind="propose_slots",
    language="en",
    duration_minutes=30,
    slots=(slot(3, 10), slot(4, 10)),
    opening_line="Thanks, a few times:",
)


def test_a_good_plan_becomes_one_pending_action_with_the_full_email() -> None:
    s = make()
    assert s.handler.handle(plan(s, PROPOSE)) == "pending_action"
    payload, digest, expiry = s.actions.actions[(s.user, s.task)]
    assert payload["to"] == ["dana@example.org"]
    assert payload["subject"] == "Re: Quick call?"
    assert payload["gmail_thread_id"] == "g-thread"
    assert "sent by my automated scheduling assistant" in payload["body"]
    assert digest.startswith("sha256:")
    assert expiry == datetime(2026, 11, 2, 18, tzinfo=TZ)


def test_e8_the_same_plan_twice_creates_one_action() -> None:
    s = make()
    s.handler.handle(plan(s, PROPOSE))
    assert s.handler.handle(plan(s, PROPOSE)) == "duplicate"
    assert len(s.actions.actions) == 1


@pytest.mark.parametrize("field_name", ["task_id", "user_id", "thread_id"])
def test_t13_a_plan_for_a_task_we_did_not_issue_is_dropped(field_name: str) -> None:
    s = make()
    result = s.handler.handle(plan(s, PROPOSE, **{field_name: uuid4()}))
    assert result == "rejected_unknown_task"
    assert s.actions.actions == {}
    assert any(kind == "plan_task_mismatch" for _, kind in s.mail.security_events)


def test_e1_a_slot_that_got_busy_since_the_agent_looked_is_rejected() -> None:
    busy = event(10, 11)  # 3 November 10:00-11:00, from test_calendar
    s = make([busy])
    assert s.handler.handle(plan(s, PROPOSE)) == "rejected_by_guard"
    assert s.actions.actions == {}
    assert s.actions.questions[(s.user, s.task)] == GUARD_REJECTED_QUESTION
    assert any(kind == "policy_guard_rejected" for _, kind in s.mail.security_events)


def test_e13_calendar_failure_on_recheck_asks_the_user() -> None:
    s = make(RuntimeError("down"))
    assert s.handler.handle(plan(s, PROPOSE)) == "question"
    assert s.actions.actions == {}


def test_uc_m7_ask_user_becomes_a_question() -> None:
    s = make()
    decision = AskUser(kind="ask_user", question="אחרי איזה חג?")
    assert s.handler.handle(plan(s, decision)) == "question"
    assert s.actions.questions[(s.user, s.task)] == "אחרי איזה חג?"


def test_not_a_request_closes_the_thread() -> None:
    s = make()
    assert s.handler.handle(plan(s, NotAMeetingRequest(kind="not_a_meeting_request"))) == "closed"
    assert s.actions.closed == [s.thread]
