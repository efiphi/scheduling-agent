"""Executing approved actions (executor.py), with fakes: invariants 3 and 4, T3, T5, E1, E8."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from google.auth.exceptions import RefreshError
from mail_fakes import FakeMailStore
from test_calendar import event
from test_free_busy_responder import FakeCalendar

from google_gateway.calendar import CalendarEvent
from google_gateway.executor import Approved, Executor
from google_gateway.pending_action import content_hash
from google_gateway.token_crypto import EncryptedToken

TZ = ZoneInfo("Asia/Jerusalem")
START = datetime(2026, 11, 3, 10, tzinfo=TZ)
PAYLOAD: dict[str, Any] = {
    "kind": "reply_with_slots",
    "gmail_thread_id": "g-thread",
    "to": ["dana@example.org"],
    "subject": "Re: Quick call?",
    "body": "Hi\n\n--\nsent by my assistant",
    "slots": [{"start": START.isoformat(), "end": (START + timedelta(minutes=30)).isoformat()}],
    "time_zone": "Asia/Jerusalem",
}


def approved(**changes: Any) -> Approved:
    digest = content_hash(PAYLOAD)
    values: dict[str, Any] = {
        "status": "approved",
        "thread_id": uuid4(),
        "payload": PAYLOAD,
        "content_hash": digest,
        "idempotency_key": uuid4(),
        "approval_hash": digest,
        "approval_used": False,
        "user_active": True,
        "participants": ("dana@example.org",),
    }
    values.update(changes)
    return Approved(**values)


@dataclass
class FakeExecutionStore:
    action: Approved | None
    claimed: bool = False
    result: tuple[str, str] | None = None  # ("executed", gmail id) or ("failed", reason)
    security_events: list[str] = field(default_factory=list)

    def load(self, user_id: UUID, action_id: UUID) -> Approved | None:
        return self.action

    def claim(self, user_id: UUID, action_id: UUID) -> bool:
        if self.claimed or self.action is None or self.action.status != "approved":
            return False
        self.claimed = True
        return True

    def executed(self, user_id: UUID, action_id: UUID, gmail_message_id: str) -> None:
        self.result = ("executed", gmail_message_id)

    def failed(
        self, user_id: UUID, action_id: UUID, thread_id: UUID, reason: str, question: str
    ) -> None:
        self.result = ("failed", reason)

    def security_event(self, user_id: UUID, kind: str, details: dict[str, Any]) -> None:
        self.security_events.append(kind)


@dataclass
class FakeSender:
    sent_before: str | None = None
    error: Exception | None = None
    sent: list[tuple[bytes, str]] = field(default_factory=list)

    def latest_message_id(self, gmail_thread_id: str) -> str | None:
        return "<original@example.org>"

    def already_sent(self, idempotency_key: UUID) -> str | None:
        return self.sent_before

    def send(self, raw: bytes, gmail_thread_id: str) -> str:
        if self.error:
            raise self.error
        self.sent.append((raw, gmail_thread_id))
        return "gmail-123"


@dataclass
class FakeWriter:
    created: list[tuple[UUID, dict[str, Any]]] = field(default_factory=list)

    def create_event(self, idempotency_key: UUID, payload: dict[str, Any]) -> str:
        self.created.append((idempotency_key, payload))
        return idempotency_key.hex


@contextmanager
def free_lock(user_id: UUID) -> Iterator[bool]:
    yield True


def run(
    action: Approved | None,
    *,
    events: list[CalendarEvent] | Exception | None = None,
    sender: FakeSender | None = None,
    writer: FakeWriter | None = None,
) -> tuple[str, FakeExecutionStore, FakeSender]:
    mail = FakeMailStore()
    user = mail.add_user()
    store, sender = FakeExecutionStore(action), sender or FakeSender()
    used_writer = writer or FakeWriter()
    calendar = FakeCalendar([] if events is None else events)

    def open_calendar(user_id: UUID, token: EncryptedToken, time_zone: str) -> FakeCalendar:
        return calendar

    def open_sender(user_id: UUID, token: EncryptedToken) -> FakeSender:
        return sender

    def open_writer(user_id: UUID, token: EncryptedToken) -> FakeWriter:
        return used_writer

    executor = Executor(
        store=store,
        mail=mail,
        open_calendar=open_calendar,
        open_sender=open_sender,
        open_writer=open_writer,
        lock=free_lock,
    )
    return executor.execute(user, uuid4()), store, sender


def test_an_approved_action_is_sent_once_in_its_thread() -> None:
    outcome, store, sender = run(approved())
    assert outcome == "executed"
    assert store.result == ("executed", "gmail-123")
    [(raw, thread)] = sender.sent
    assert thread == "g-thread"
    assert b"To: dana@example.org" in raw and b"In-Reply-To: <original@example.org>" in raw


@pytest.mark.parametrize("field_name", ["payload", "content_hash", "approval_hash"])
def test_t3_any_hash_disagreement_stops_the_send(field_name: str) -> None:
    options: dict[str, dict[str, Any]] = {
        "payload": {"payload": {**PAYLOAD, "to": ["dana@example.org", "attacker@example.org"]}},
        "content_hash": {"content_hash": "sha256:" + "0" * 64},
        "approval_hash": {"approval_hash": "sha256:" + "1" * 64},
    }
    changes = options[field_name]
    outcome, store, sender = run(approved(**changes))
    assert outcome == "failed_hash_mismatch"
    assert sender.sent == []
    assert "execute_refused_hash_mismatch" in store.security_events


@pytest.mark.parametrize("changes", [{"approval_hash": None}, {"approval_used": True}])
def test_t10_no_unused_approval_no_send(changes: dict[str, Any]) -> None:
    outcome, _, sender = run(approved(**changes))
    assert outcome == "failed_no_valid_approval" and sender.sent == []


def test_t5_a_recipient_no_longer_in_the_thread_stops_the_send() -> None:
    outcome, _, sender = run(approved(participants=("someone-else@example.org",)))
    assert outcome == "failed_recipient_not_in_thread" and sender.sent == []


def test_invariant_12_a_paused_user_sends_nothing() -> None:
    outcome, _, sender = run(approved(user_active=False))
    assert outcome == "failed_user_not_active" and sender.sent == []


def test_e1_a_slot_that_got_busy_after_approval_stops_the_send() -> None:
    busy = event(10, 11)  # 3 November 10:00-11:00
    outcome, store, sender = run(approved(), events=[busy])
    assert outcome == "failed_slot_taken" and sender.sent == []
    assert not store.claimed


def test_e8_already_sent_before_a_crash_is_not_sent_again() -> None:
    outcome, store, sender = run(approved(), sender=FakeSender(sent_before="gmail-old"))
    assert outcome == "executed" and sender.sent == []
    assert store.result == ("executed", "gmail-old")


def test_e8_an_interrupted_action_is_never_resent_blindly() -> None:
    outcome, _, sender = run(approved(status="executing"))
    assert outcome == "failed_interrupted" and sender.sent == []
    recovered, store2, _ = run(
        approved(status="executing"), sender=FakeSender(sent_before="gmail-1")
    )
    assert recovered == "executed" and store2.result == ("executed", "gmail-1")


@pytest.mark.parametrize("status", ["executed", "rejected", "failed", "pending"])
def test_only_approved_actions_are_executed(status: str) -> None:
    outcome, _, sender = run(approved(status=status))
    assert outcome == "not_approved" and sender.sent == []


def test_e13_a_rejected_token_fails_visibly() -> None:
    outcome, store, _ = run(approved(), sender=FakeSender(error=RefreshError("invalid_grant")))  # type: ignore[no-untyped-call]
    assert outcome == "failed_token_rejected"
    assert store.result == ("failed", "token_rejected")


def test_unknown_action_is_a_security_event() -> None:
    outcome, store, _ = run(None)
    assert outcome == "unknown" and store.security_events == ["execute_unknown_action"]


def test_header_injection_is_refused_by_the_message_builder() -> None:
    bad = {**PAYLOAD, "subject": "Hi\r\nBcc: attacker@example.org"}
    action = replace(
        approved(), payload=bad, content_hash=content_hash(bad), approval_hash=content_hash(bad)
    )
    outcome, _, sender = run(action)
    assert outcome == "failed_send_error" and sender.sent == []


EVENT: dict[str, Any] = {
    **PAYLOAD,
    "kind": "create_event",
    "subject": "Meeting: Quick call?",
    "body": "created by my assistant",
}


def event_action(**changes: Any) -> Approved:
    digest = content_hash(EVENT)
    return approved(payload=EVENT, content_hash=digest, approval_hash=digest, **changes)


def test_uc_m2_an_approved_event_is_created_with_a_fixed_id_and_no_email() -> None:
    writer = FakeWriter()
    action = event_action()
    outcome, store, sender = run(action, writer=writer)
    assert outcome == "executed" and sender.sent == []
    [(key, payload)] = writer.created
    assert key == action.idempotency_key and payload["to"] == ["dana@example.org"]
    assert store.result == ("executed", action.idempotency_key.hex)


def test_e8_an_interrupted_event_is_safely_created_again() -> None:
    # Same event id: Google finds the one event instead of creating a second.
    writer = FakeWriter()
    outcome, _, _ = run(event_action(status="executing"), writer=writer)
    assert outcome == "executed" and len(writer.created) == 1


def test_t5_an_event_attendee_not_in_the_thread_stops_it() -> None:
    writer = FakeWriter()
    outcome, _, _ = run(event_action(participants=("other@example.org",)), writer=writer)
    assert outcome == "failed_recipient_not_in_thread" and writer.created == []


def test_e1_an_event_slot_that_became_busy_is_not_created() -> None:
    writer = FakeWriter()
    outcome, _, _ = run(event_action(), events=[event(10, 11)], writer=writer)
    assert outcome == "failed_slot_taken" and writer.created == []
