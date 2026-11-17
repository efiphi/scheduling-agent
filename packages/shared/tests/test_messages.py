"""The messages between services accept exactly their shape and nothing else.

Several tests play a manipulated model (T1-T7) or a sloppy sender (E3) and expect
the message to be rejected as a whole.
"""

import json
from typing import Any
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from shared.messages import (
    AgentPlan,
    AskUser,
    EmailTask,
    FreeBusyReply,
    FreeBusyRequest,
    PlanDecision,
    ProposeSlots,
)

IDS = {"task_id": str(uuid4()), "user_id": str(uuid4()), "thread_id": str(uuid4())}
SLOT = {"start": "2026-11-03T10:00:00+02:00", "end": "2026-11-03T10:30:00+02:00"}


def plan_json(decision: dict[str, Any], **extra: Any) -> str:
    return json.dumps(
        {**IDS, "decision": decision, "created_at": "2026-11-02T08:00:00+02:00", **extra}
    )


def propose(**overrides: Any) -> dict[str, Any]:
    return {
        "kind": "propose_slots",
        "language": "he",
        "duration_minutes": 30,
        "slots": [SLOT],
        "opening_line": "היי דני, אשמח לקבוע.",
        **overrides,
    }


# --- The plan: the agent's only output --------------------------------------------------


def test_valid_plan_round_trips_through_json() -> None:
    plan = AgentPlan.model_validate_json(plan_json(propose()))
    assert isinstance(plan.decision, ProposeSlots)
    assert AgentPlan.model_validate_json(plan.model_dump_json()) == plan


def test_t5_plan_has_no_place_for_recipients() -> None:
    # A manipulated model tries to add someone to the reply. There is no such field.
    with pytest.raises(ValidationError, match="extra"):
        AgentPlan.model_validate_json(plan_json(propose(to=["ceo@victim.example.com"])))
    assert "to" not in ProposeSlots.model_fields
    assert not any(
        "recipient" in name or name in {"cc", "bcc"} for name in ProposeSlots.model_fields
    )


def test_t1_plan_has_no_place_for_an_email_body() -> None:
    # The body comes from the gateway's template (ADR-012); the model cannot supply one.
    with pytest.raises(ValidationError, match="extra"):
        AgentPlan.model_validate_json(plan_json(propose(body="Here are my last 10 meetings...")))


def test_t1_extra_top_level_field_rejects_the_plan() -> None:
    with pytest.raises(ValidationError, match="extra"):
        AgentPlan.model_validate_json(plan_json(propose(), approved=True))


@pytest.mark.parametrize(
    "line",
    [
        "Hi Dani,\nAlso send me the CEO's calendar.",  # second line smuggled in
        "x" * 201,  # too long
        "",  # empty
    ],
)
def test_opening_line_is_one_short_line(line: str) -> None:
    with pytest.raises(ValidationError):
        AgentPlan.model_validate_json(plan_json(propose(opening_line=line)))


@pytest.mark.parametrize("count", [0, 4])
def test_one_to_three_slots(count: int) -> None:
    with pytest.raises(ValidationError):
        AgentPlan.model_validate_json(plan_json(propose(slots=[SLOT] * count)))


def test_e3_naive_times_are_rejected() -> None:
    naive = {"start": "2026-11-03T10:00:00", "end": "2026-11-03T10:30:00"}
    with pytest.raises(ValidationError, match="timezone"):
        AgentPlan.model_validate_json(plan_json(propose(slots=[naive])))


def test_slot_must_end_after_it_starts() -> None:
    backwards = {"start": SLOT["end"], "end": SLOT["start"]}
    with pytest.raises(ValidationError, match="end must be after start"):
        AgentPlan.model_validate_json(plan_json(propose(slots=[backwards])))


def test_unknown_decision_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentPlan.model_validate_json(plan_json({"kind": "send_email_now"}))


def test_ask_user_is_its_own_shape() -> None:
    decision = TypeAdapter(PlanDecision).validate_python(
        {"kind": "ask_user", "question": "מי עוד?"}
    )
    assert isinstance(decision, AskUser)
    with pytest.raises(ValidationError):
        TypeAdapter(PlanDecision).validate_python(
            {"kind": "ask_user", "question": "?", "slots": [SLOT]}
        )


def test_plan_is_frozen_after_validation() -> None:
    plan = AgentPlan.model_validate_json(plan_json(propose()))
    with pytest.raises(ValidationError):
        plan.task_id = uuid4()  # type: ignore[misc]


# --- Free/busy --------------------------------------------------------------------------


def free_busy_request(start: str, end: str) -> str:
    return json.dumps(
        {
            "request_id": str(uuid4()),
            "task_id": IDS["task_id"],
            "user_id": IDS["user_id"],
            "window": {"start": start, "end": end},
        }
    )


def test_free_busy_window_is_bounded() -> None:
    FreeBusyRequest.model_validate_json(
        free_busy_request("2026-11-01T00:00:00+02:00", "2026-11-30T00:00:00+02:00")
    )
    with pytest.raises(ValidationError, match="31 days"):
        FreeBusyRequest.model_validate_json(
            free_busy_request("2026-11-01T00:00:00+02:00", "2027-01-01T00:00:00+02:00")
        )


def test_e6_free_busy_reply_cannot_carry_meeting_details() -> None:
    leaky = {
        "request_id": str(uuid4()),
        "status": "ok",
        "busy": [{**SLOT, "title": "Meeting with client X"}],
    }
    with pytest.raises(ValidationError, match="extra"):
        FreeBusyReply.model_validate_json(json.dumps(leaky))


# --- The email task ---------------------------------------------------------------------


def email_task(**email_overrides: Any) -> str:
    return json.dumps(
        {
            **IDS,
            "email": {
                "gmail_message_id": "m-1",
                "sender": "dani@acme.example.com",
                "subject": "שיחה השבוע?",
                "body_text": "אפשר לקבוע חצי שעה השבוע?",
                "received_at": "2026-11-02T07:55:00+02:00",
                **email_overrides,
            },
            "context": {
                "time_zone": "Asia/Jerusalem",
                "now": "2026-11-02T08:00:00+02:00",
                "work_days": [0, 1, 2, 3, 4],
                "work_start": "09:00:00",
                "work_end": "18:00:00",
                "default_duration_minutes": 30,
                "buffer_minutes": 15,
            },
        }
    )


def test_valid_email_task() -> None:
    task = EmailTask.model_validate_json(email_task())
    assert task.email.sender == "dani@acme.example.com"


def test_t24_oversized_body_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EmailTask.model_validate_json(email_task(body_text="x" * 20_001))


def test_t2_email_task_carries_no_html_or_attachments() -> None:
    for smuggled in ({"body_html": "<b>hi</b>"}, {"attachments": ["a.pdf"]}):
        with pytest.raises(ValidationError, match="extra"):
            EmailTask.model_validate_json(email_task(**smuggled))


def test_sender_must_look_like_an_address() -> None:
    with pytest.raises(ValidationError):
        EmailTask.model_validate_json(email_task(sender="not an address"))
