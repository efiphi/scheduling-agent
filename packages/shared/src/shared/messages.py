"""Messages between the services, carried as JSON over Redis Streams (ADR-004, ADR-011).

    google-gateway --EmailTask--------> agent
    agent ---------FreeBusyRequest----> google-gateway
    google-gateway --FreeBusyReply----> agent
    agent ---------AgentPlan----------> google-gateway  (then the policy guard)

Every message is a StrictModel: an unknown field rejects the whole message (T1-T7).
Design choices that carry security weight:

- The agent's plan has **no recipients field**. Who receives a reply is decided by
  google-gateway from the people already in the thread (T5). A manipulated model has
  nowhere to write an extra address.
- The plan has no email body either: only slots and a short opening line. The gateway
  builds the email from a template and adds the disclosure line (invariant 10, ADR-012).
- Free/busy carries intervals only: no titles, attendees or descriptions (invariant 5, E6).
- Every time is timezone-aware; a naive "10:00" is rejected (E3).
- Untrusted email text is a distinct type and has size limits (T1, T24).
"""

from datetime import time, timedelta
from typing import Annotated, Literal, NewType, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from shared.schema import StrictModel

SCHEMA_VERSION: Literal[1] = 1

# Text that came from outside the system: data to read, never instructions to follow
# (invariant 2). A separate type makes that visible wherever it is passed around.
UntrustedText = NewType("UntrustedText", str)

EmailAddress = Annotated[str, StringConstraints(max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")]

# Caps keep a single email from costing much at the LLM (T24) or carrying a huge payload.
MAX_SUBJECT_CHARS = 500
MAX_BODY_CHARS = 20_000
MAX_FREE_BUSY_WINDOW = timedelta(days=31)


class Interval(StrictModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _ends_after_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


# --- gateway -> agent ------------------------------------------------------------------


class UntrustedEmail(StrictModel):
    """The email as the gateway read it: plain text only, no HTML, no attachments (T2)."""

    gmail_message_id: str = Field(max_length=200)
    sender: EmailAddress
    subject: Annotated[UntrustedText, StringConstraints(max_length=MAX_SUBJECT_CHARS)]
    body_text: Annotated[UntrustedText, StringConstraints(max_length=MAX_BODY_CHARS)]
    received_at: AwareDatetime


class AgentContext(StrictModel):
    """Only what extraction and slot choice need; never other meetings (ADR-011)."""

    time_zone: str = Field(max_length=64)
    now: AwareDatetime
    work_days: tuple[int, ...] = Field(min_length=1, max_length=7)
    work_start: time
    work_end: time
    default_duration_minutes: int = Field(ge=5, le=480)
    buffer_minutes: int = Field(ge=0, le=120)


class EmailTask(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    task_id: UUID
    user_id: UUID
    thread_id: UUID
    email: UntrustedEmail
    context: AgentContext


# --- agent <-> gateway: free/busy -------------------------------------------------------


class FreeBusyRequest(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    request_id: UUID
    task_id: UUID
    user_id: UUID
    window: Interval

    @model_validator(mode="after")
    def _window_is_bounded(self) -> Self:
        if self.window.end - self.window.start > MAX_FREE_BUSY_WINDOW:
            raise ValueError("free/busy window is limited to 31 days")
        return self


class FreeBusyReply(StrictModel):
    """Busy intervals only. There is no field for titles, attendees or descriptions (E6)."""

    schema_version: Literal[1] = SCHEMA_VERSION
    request_id: UUID
    status: Literal["ok", "unavailable"]
    busy: tuple[Interval, ...] = ()


# --- agent -> gateway: the plan ---------------------------------------------------------

# One short sentence. Content checks (links, addresses, commitments) are the policy
# guard's job in google-gateway; the schema enforces the shape.
OpeningLine = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]*$")]


class ProposeSlots(StrictModel):
    """Reply in the thread with 1-3 slots. Recipients come from the thread, not from here."""

    kind: Literal["propose_slots"]
    language: Literal["he", "en"]
    duration_minutes: int = Field(ge=5, le=480)
    slots: tuple[Interval, ...] = Field(min_length=1, max_length=3)
    opening_line: OpeningLine


class AskUser(StrictModel):
    """The request is unclear: ask the user, do not guess (UC-M7)."""

    kind: Literal["ask_user"]
    question: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class NotAMeetingRequest(StrictModel):
    """The filter let it through, but it is not a scheduling request (E9)."""

    kind: Literal["not_a_meeting_request"]


PlanDecision = Annotated[ProposeSlots | AskUser | NotAMeetingRequest, Field(discriminator="kind")]


class AgentPlan(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    task_id: UUID
    user_id: UUID
    thread_id: UUID
    decision: PlanDecision
    created_at: AwareDatetime


__all__ = [
    "SCHEMA_VERSION",
    "AgentContext",
    "AgentPlan",
    "AskUser",
    "EmailTask",
    "FreeBusyReply",
    "FreeBusyRequest",
    "Interval",
    "NotAMeetingRequest",
    "PlanDecision",
    "ProposeSlots",
    "UntrustedEmail",
    "UntrustedText",
]
