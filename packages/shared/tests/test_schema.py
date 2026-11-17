import pytest
from pydantic import ValidationError

from shared.schema import StrictModel


class ReplyPlan(StrictModel):
    """A minimal stand-in for an agent plan, for testing the base class only."""

    thread_id: str
    slot_count: int


def test_valid_message_is_accepted() -> None:
    plan = ReplyPlan(thread_id="t-1", slot_count=2)
    assert plan.slot_count == 2


def test_t1_unknown_field_rejects_the_whole_message() -> None:
    # A manipulated model tries to smuggle an extra instruction into its output.
    with pytest.raises(ValidationError, match="extra"):
        ReplyPlan.model_validate(
            {"thread_id": "t-1", "slot_count": 2, "also_send_to": "attacker@example.com"}
        )


def test_no_silent_type_coercion() -> None:
    with pytest.raises(ValidationError):
        ReplyPlan.model_validate({"thread_id": "t-1", "slot_count": "2"})


def test_validated_message_cannot_be_modified() -> None:
    plan = ReplyPlan(thread_id="t-1", slot_count=2)
    with pytest.raises(ValidationError):
        # mypy already rejects this line statically; the test proves it also fails at runtime.
        plan.slot_count = 3  # type: ignore[misc]
