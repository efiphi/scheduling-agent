"""Fakes for the mail poller: Gmail, the database and Redis, in memory. Synthetic data only."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID, uuid4

from google_gateway.gmail import HistoryExpired, MessageMeta, MessageRef
from google_gateway.mail_store import Mailbox
from google_gateway.token_crypto import EncryptedToken
from shared.messages import AgentContext, EmailTask

USER_EMAIL = "demo-user@example.com"
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def meta(
    message_id: str = "m1",
    *,
    thread_id: str | None = None,
    sender: str = "Dana Example <dana@example.org>",
    subject: str = "Can we schedule a call?",
    snippet: str = "",
    labels: tuple[str, ...] = ("INBOX",),
    to: str = USER_EMAIL,
    cc: str = "",
    extra: dict[str, str] | None = None,
    **headers: str,
) -> MessageMeta:
    all_headers = {"from": sender, "to": to, "subject": subject}
    if cc:
        all_headers["cc"] = cc
    for name, value in {**headers, **(extra or {})}.items():
        all_headers[name.replace("_", "-").lower()] = value
    return MessageMeta(
        message_id=message_id,
        thread_id=thread_id or f"t-{message_id}",
        labels=frozenset(labels),
        headers=all_headers,
        snippet=snippet,
        received_at=NOW,
    )


@dataclass
class FakeGmail:
    messages: dict[str, MessageMeta] = field(default_factory=dict)
    bodies: dict[str, str] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)  # message ids added since last poll
    history_id: str = "100"
    expired: bool = False
    error: Exception | None = None
    bodies_read: list[str] = field(default_factory=list)

    def add(self, message: MessageMeta, body: str = "body text") -> None:
        self.messages[message.message_id] = message
        self.bodies[message.message_id] = body
        self.history.append(message.message_id)

    def current_history_id(self) -> str:
        if self.error:
            raise self.error
        return self.history_id

    def added_since(self, history_id: str) -> tuple[list[MessageRef], str]:
        if self.error:
            raise self.error
        if self.expired:
            raise HistoryExpired
        refs = [MessageRef(m, self.messages[m].thread_id) for m in self.history]
        return refs, str(int(self.history_id) + len(self.history))

    def recent(self, days: int) -> list[MessageRef]:
        return [MessageRef(m.message_id, m.thread_id) for m in self.messages.values()]

    def message_metadata(self, message_id: str) -> MessageMeta:
        return self.messages[message_id]

    def message_body(self, message_id: str) -> str:
        self.bodies_read.append(message_id)
        return self.bodies[message_id]


@dataclass
class FakeMailStore:
    users: dict[UUID, Mailbox] = field(default_factory=dict)
    threads: dict[tuple[UUID, str], tuple[UUID, list[str]]] = field(default_factory=dict)
    tracked: set[tuple[UUID, str]] = field(default_factory=set)
    skipped: list[tuple[UUID, str, str]] = field(default_factory=list)
    expired: set[UUID] = field(default_factory=set)
    audits: list[tuple[UUID, str, dict[str, Any]]] = field(default_factory=list)
    security_events: list[tuple[UUID, str]] = field(default_factory=list)

    def add_user(self, history_id: str | None = "100") -> UUID:
        user_id = uuid4()
        self.users[user_id] = Mailbox(USER_EMAIL, EncryptedToken(b"x", 1), history_id)
        return user_id

    def users_to_poll(self) -> list[UUID]:
        return [u for u in self.users if u not in self.expired]

    def mailbox(self, user_id: UUID) -> Mailbox | None:
        return None if user_id in self.expired else self.users.get(user_id)

    def set_history_id(self, user_id: UUID, history_id: str) -> None:
        box = self.users[user_id]
        self.users[user_id] = Mailbox(box.email, box.token, history_id)

    def mark_expired(self, user_id: UUID) -> None:
        self.expired.add(user_id)
        self.security_events.append((user_id, "google_token_rejected"))

    def is_tracked_thread(self, user_id: UUID, gmail_thread_id: str) -> bool:
        return (user_id, gmail_thread_id) in self.tracked

    def upsert_thread(self, user_id: UUID, gmail_thread_id: str, participants: list[str]) -> UUID:
        thread_id, known = self.threads.get((user_id, gmail_thread_id), (uuid4(), []))
        self.threads[(user_id, gmail_thread_id)] = (thread_id, sorted({*known, *participants}))
        return thread_id

    def record_skipped(
        self, user_id: UUID, sender: str, subject: str, received_at: datetime
    ) -> None:
        self.skipped.append((user_id, sender, subject))

    def agent_context(self, user_id: UUID, now: datetime) -> AgentContext:
        return AgentContext(
            time_zone="Asia/Jerusalem",
            now=now,
            work_days=(0, 1, 2, 3, 4),
            work_start=time(9),
            work_end=time(18),
            default_duration_minutes=30,
            buffer_minutes=15,
        )

    def audit(self, user_id: UUID, action: str, details: dict[str, Any]) -> None:
        self.audits.append((user_id, action, details))

    def security_event(self, user_id: UUID, kind: str, details: dict[str, Any]) -> None:
        self.security_events.append((user_id, kind))


@dataclass
class FakeCoordination:
    locked: set[UUID] = field(default_factory=set)
    handled: set[tuple[UUID, str]] = field(default_factory=set)
    allow: int = 1000  # how many rate slots before refusing
    queue: list[EmailTask] = field(default_factory=list)

    @contextmanager
    def lock_user(self, user_id: UUID) -> Iterator[bool]:
        yield user_id not in self.locked

    def already_handled(self, user_id: UUID, message_id: str) -> bool:
        return (user_id, message_id) in self.handled

    def mark_handled(self, user_id: UUID, message_id: str) -> None:
        self.handled.add((user_id, message_id))

    def take_rate_slot(self, user_id: UUID, sender: str) -> bool:
        self.allow -= 1
        return self.allow >= 0

    def enqueue(self, task: EmailTask) -> None:
        self.queue.append(task)

    def task_owner(self, task_id: UUID) -> UUID | None:
        return next((t.user_id for t in self.queue if t.task_id == task_id), None)
