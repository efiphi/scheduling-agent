"""Shared synthetic inputs for the agent tests."""

from datetime import UTC, date, datetime, time
from typing import Any
from uuid import uuid4

from agent.extraction import ExtractionForm, MeetingRequest, ModelAnswer, Usage
from shared.messages import AgentContext, EmailTask, UntrustedEmail, UntrustedText

# Monday 2 November 2026, 09:00 in Israel (07:00 UTC).
NOW = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
CONTEXT = AgentContext(
    time_zone="Asia/Jerusalem",
    now=NOW,
    work_days=(0, 1, 2, 3, 4),  # Sunday to Thursday
    work_start=time(9),
    work_end=time(18),
    default_duration_minutes=30,
    buffer_minutes=15,
)


def request(**changes: Any) -> MeetingRequest:
    values: dict[str, Any] = {
        "language": "en",
        "duration_minutes": 30,
        "earliest": date(2026, 11, 3),
        "latest": date(2026, 11, 5),
        "time_of_day": "any",
        "opening_line": "Thanks, here are a few times that work.",
    }
    values.update(changes)
    return MeetingRequest(**values)


def task(body: str = "Can we meet Tuesday?") -> EmailTask:
    return EmailTask(
        task_id=uuid4(),
        user_id=uuid4(),
        thread_id=uuid4(),
        email=UntrustedEmail(
            gmail_message_id="m1",
            sender="dana@example.org",
            subject=UntrustedText("Meeting"),
            body_text=UntrustedText(body),
            received_at=NOW,
        ),
        context=CONTEXT,
    )


def form(**changes: Any) -> ExtractionForm:
    values: dict[str, Any] = {
        "is_meeting_request": True,
        "language": "en",
        "duration_minutes": 30,
        "earliest_date": date(2026, 11, 3),
        "latest_date": date(2026, 11, 5),
        "time_of_day": "any",
        "stated_weekday": None,
        "unclear": False,
        "question_for_user": None,
        "opening_line": "Thanks, here are a few times that work.",
    }
    values.update(changes)
    return ExtractionForm(**values)


class FakeFiller:
    def __init__(self, answer: ModelAnswer | None = None) -> None:
        self.answer = answer or ModelAnswer(form(), "end_turn", Usage(1000, 200))
        self.calls = 0

    def fill(self, system: str, user: str) -> ModelAnswer:
        self.calls += 1
        return self.answer
