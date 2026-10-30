"""Executing approved actions: the only place that sends email (step 1.10, invariants 3, 4).

    python -m google_gateway.executor

The api puts only an action id on the approved-actions stream. Nothing from the api is
trusted: everything is re-read from the database and re-checked, under a per-user lock in
Redis so two approvals cannot race each other (E1):
1. The action is "approved" and has an unused approval record.
2. Three hashes agree: the approval's, the action's, and one recomputed here from the
   stored payload. A payload changed after approval, by anyone, stops here (T3, T10).
3. The user is still active (not paused, invariant 12), and every recipient is still a
   participant of the thread (T5).
4. Every slot is still free on a fresh calendar read (E1).
5. The action is claimed ("executing") and the approval marked used, in one transaction.
6. Gmail is asked whether a message with this action's Message-ID already exists; only if
   not is the email sent (E8). Then the action is "executed".
Any failed check marks the action "failed" with a reason code, and the user gets a
question instead of a silent failure (E13). An action found "executing" after a crash is
never re-sent blindly: if Gmail has it, it is "executed", otherwise "failed".
"""

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from google.auth.exceptions import RefreshError
from redis import Redis
from redis.exceptions import LockError, ResponseError
from sqlalchemy import Engine, text

from db.session import set_user_context
from google_gateway.calendar import busy_intervals
from google_gateway.events import write_audit, write_security_event
from google_gateway.free_busy_responder import OpenCalendar
from google_gateway.gmail_sender import MailSender, build_message
from google_gateway.mail_store import MailStore
from google_gateway.pending_action import content_hash
from google_gateway.token_crypto import EncryptedToken
from shared.messages import Interval
from shared.streams import APPROVED_ACTIONS

logger = logging.getLogger(__name__)

GROUP = "gateway"
BLOCK_MS = 5_000
LOCK_SECONDS = 120

QUESTIONS = {
    "slot_taken": (
        "אחד המועדים שאישרת כבר לא פנוי, ולכן המייל לא נשלח. כדאי לבקש מהסוכן מועדים חדשים."
    ),
    "default": "שליחת המייל שאישרת נכשלה. שום דבר לא נשלח. כדאי לבדוק את הפעולה בהיסטוריה.",
}


@dataclass(frozen=True)
class Approved:
    status: str
    thread_id: UUID
    payload: dict[str, Any]
    content_hash: str
    idempotency_key: UUID
    approval_hash: str | None
    approval_used: bool
    user_active: bool
    participants: tuple[str, ...]


class ExecutionStore(Protocol):
    def load(self, user_id: UUID, action_id: UUID) -> Approved | None: ...

    def claim(self, user_id: UUID, action_id: UUID) -> bool: ...

    def executed(self, user_id: UUID, action_id: UUID, gmail_message_id: str) -> None: ...

    def failed(
        self, user_id: UUID, action_id: UUID, thread_id: UUID, reason: str, question: str
    ) -> None: ...

    def security_event(self, user_id: UUID, kind: str, details: dict[str, Any]) -> None: ...


OpenSender = Callable[[UUID, EncryptedToken], MailSender]
UserLock = Callable[[UUID], AbstractContextManager[bool]]


@dataclass(frozen=True)
class Executor:
    store: ExecutionStore
    mail: MailStore
    open_calendar: OpenCalendar
    open_sender: OpenSender
    lock: UserLock

    def execute(self, user_id: UUID, action_id: UUID) -> str:
        with self.lock(user_id) as locked:
            if not locked:
                return "locked"  # left pending in the stream; retried by the next read
            return self._execute(user_id, action_id)

    def _execute(self, user_id: UUID, action_id: UUID) -> str:
        action = self.store.load(user_id, action_id)
        if action is None:
            self.store.security_event(user_id, "execute_unknown_action", {})
            return "unknown"
        mailbox = self.mail.mailbox(user_id)
        if action.status == "executing":
            return self._recover(user_id, action_id, action, mailbox)
        if action.status != "approved":
            return "not_approved"  # already executed, rejected or failed: nothing to do

        recomputed = content_hash(action.payload)
        if action.approval_hash is None or action.approval_used:
            return self._fail(user_id, action_id, action, "no_valid_approval", security=True)
        if not (action.approval_hash == action.content_hash == recomputed):
            return self._fail(user_id, action_id, action, "hash_mismatch", security=True)
        if not action.user_active or mailbox is None:
            return self._fail(user_id, action_id, action, "user_not_active")
        recipients = {r.lower() for r in action.payload.get("to", [])}
        if not recipients or not recipients <= {p.lower() for p in action.participants}:
            return self._fail(user_id, action_id, action, "recipient_not_in_thread", security=True)

        try:
            if not self._slots_still_free(user_id, mailbox.token, action.payload):
                return self._fail(user_id, action_id, action, "slot_taken")
            if not self.store.claim(user_id, action_id):
                return "already_claimed"
            sender = self.open_sender(user_id, mailbox.token)
            gmail_id = sender.already_sent(action.idempotency_key) or self._send(sender, action)
        except RefreshError:
            self.mail.mark_expired(user_id)
            return self._fail(user_id, action_id, action, "token_rejected")
        except Exception as exc:
            logger.error("execution failed: action_id=%s error=%s", action_id, type(exc).__name__)
            return self._fail(user_id, action_id, action, "send_error")
        self.store.executed(user_id, action_id, gmail_id)
        return "executed"

    def _send(self, sender: MailSender, action: Approved) -> str:
        payload = action.payload
        raw = build_message(
            to=list(payload["to"]),
            subject=str(payload["subject"]),
            body=str(payload["body"]),
            idempotency_key=action.idempotency_key,
            in_reply_to=sender.latest_message_id(str(payload["gmail_thread_id"])),
        )
        return sender.send(raw, str(payload["gmail_thread_id"]))

    def _recover(self, user_id: UUID, action_id: UUID, action: Approved, mailbox: Any) -> str:
        # A previous run claimed it and stopped. Never send blindly: ask Gmail first.
        if mailbox is not None:
            try:
                sent = self.open_sender(user_id, mailbox.token).already_sent(action.idempotency_key)
            except Exception:
                sent = None
            if sent:
                self.store.executed(user_id, action_id, sent)
                return "executed"
        return self._fail(user_id, action_id, action, "interrupted")

    def _slots_still_free(
        self, user_id: UUID, token: EncryptedToken, payload: dict[str, Any]
    ) -> bool:
        # Stored as JSON text in the payload, so parsed as JSON (strict models take no strings
        # for datetimes in Python mode).
        slots = [Interval.model_validate_json(json.dumps(s)) for s in payload.get("slots", [])]
        if not slots:
            return False
        window = Interval(start=min(s.start for s in slots), end=max(s.end for s in slots))
        events = self.open_calendar(user_id, token, str(payload["time_zone"])).events(window)
        busy = busy_intervals(events, window)
        return not any(s.start < b.end and b.start < s.end for s in slots for b in busy)

    def _fail(
        self,
        user_id: UUID,
        action_id: UUID,
        action: Approved,
        reason: str,
        *,
        security: bool = False,
    ) -> str:
        if security:
            self.store.security_event(
                user_id, f"execute_refused_{reason}", {"action_id": str(action_id)}
            )
        question = QUESTIONS.get(reason, QUESTIONS["default"])
        self.store.failed(user_id, action_id, action.thread_id, reason, question)
        return f"failed_{reason}"


# --- Database ---------------------------------------------------------------------------


class SqlExecutionStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load(self, user_id: UUID, action_id: UUID) -> Approved | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            row = conn.execute(
                text(
                    "SELECT a.status, a.thread_id, a.payload, a.content_hash, a.idempotency_key,"
                    " p.content_hash, p.used_at IS NOT NULL, u.status = 'active', t.participants"
                    " FROM app.pending_actions AS a"
                    " JOIN app.users AS u ON u.user_id = a.user_id"
                    " JOIN app.threads AS t ON t.user_id = a.user_id AND t.thread_id = a.thread_id"
                    " LEFT JOIN app.approvals AS p"
                    " ON p.user_id = a.user_id AND p.action_id = a.action_id"
                    " WHERE a.user_id = :u AND a.action_id = :a"
                ),
                {"u": user_id, "a": action_id},
            ).one_or_none()
        if row is None:
            return None
        return Approved(
            status=row[0],
            thread_id=UUID(str(row[1])),
            payload=dict(row[2]),
            content_hash=row[3],
            idempotency_key=UUID(str(row[4])),
            approval_hash=row[5],
            approval_used=bool(row[6]),
            user_active=bool(row[7]),
            participants=tuple(row[8]),
        )

    def claim(self, user_id: UUID, action_id: UUID) -> bool:
        # Both updates or neither: a claimed action always has a used approval.
        with self._engine.connect() as conn, conn.begin() as transaction:
            set_user_context(conn, user_id)
            claimed = conn.execute(
                text(
                    "UPDATE app.pending_actions SET status = 'executing'"
                    " WHERE user_id = :u AND action_id = :a AND status = 'approved'"
                ),
                {"u": user_id, "a": action_id},
            ).rowcount
            used = conn.execute(
                text(
                    "UPDATE app.approvals SET used_at = now()"
                    " WHERE user_id = :u AND action_id = :a AND used_at IS NULL"
                ),
                {"u": user_id, "a": action_id},
            ).rowcount
            if not (claimed and used):
                transaction.rollback()
                return False
        return True

    def executed(self, user_id: UUID, action_id: UUID, gmail_message_id: str) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                text(
                    "UPDATE app.pending_actions SET status = 'executed', executed_at = now()"
                    " WHERE user_id = :u AND action_id = :a"
                ),
                {"u": user_id, "a": action_id},
            )
            write_audit(
                conn,
                user_id,
                "action_executed",
                {"action_id": str(action_id), "gmail_message_id": gmail_message_id},
            )

    def failed(
        self, user_id: UUID, action_id: UUID, thread_id: UUID, reason: str, question: str
    ) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                text(
                    "UPDATE app.pending_actions SET status = 'failed', failure_reason = :r"
                    " WHERE user_id = :u AND action_id = :a AND status IN ('approved', 'executing')"
                ),
                {"u": user_id, "a": action_id, "r": reason},
            )
            conn.execute(
                text(
                    "INSERT INTO app.user_questions (user_id, thread_id, question)"
                    " VALUES (:u, :t, :q)"
                ),
                {"u": user_id, "t": thread_id, "q": question},
            )
            write_audit(
                conn, user_id, "action_failed", {"action_id": str(action_id), "reason": reason}
            )

    def security_event(self, user_id: UUID, kind: str, details: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            write_security_event(conn, user_id, kind, details)


# --- The process ------------------------------------------------------------------------


def redis_user_lock(redis: Redis) -> UserLock:
    @contextmanager
    def lock(user_id: UUID) -> Iterator[bool]:
        held = redis.lock(f"lock:send:{user_id}", timeout=LOCK_SECONDS, blocking_timeout=10)
        acquired = bool(held.acquire())
        try:
            yield acquired
        finally:
            if acquired:
                with suppress(LockError):  # expired while we worked: nothing to release
                    held.release()

    return lock


def run_once(redis: Redis, executor: Executor, consumer: str) -> int:
    response: Any = redis.xreadgroup(
        GROUP, consumer, {APPROVED_ACTIONS: ">"}, count=1, block=BLOCK_MS
    )
    if not response:
        return 0
    message_id, fields = response[0][1][0]
    try:
        user_id = UUID(fields[b"user_id"].decode())
        action_id = UUID(fields[b"action_id"].decode())
    except (KeyError, ValueError):
        logger.error("invalid approved-action message dropped")
    else:
        outcome = executor.execute(user_id, action_id)
        logger.info("approved action handled: action_id=%s outcome=%s", action_id, outcome)
        if outcome == "locked":
            return 1  # not acknowledged: stays pending for a retry
    redis.xack(APPROVED_ACTIONS, GROUP, message_id)
    return 1


def ensure_group(redis: Redis) -> None:
    try:
        redis.xgroup_create(APPROVED_ACTIONS, GROUP, id="0", mkstream=True)
    except ResponseError as error:
        if "BUSYGROUP" not in str(error):
            raise


def main() -> None:
    import socket

    from google_gateway.config import GatewayConfig
    from google_gateway.wiring import executor, redis_client

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)  # T22
    config = GatewayConfig.from_env()
    redis = redis_client(config)
    ensure_group(redis)
    worker = executor(config)
    while True:
        run_once(redis, worker, socket.gethostname())


if __name__ == "__main__":
    main()
