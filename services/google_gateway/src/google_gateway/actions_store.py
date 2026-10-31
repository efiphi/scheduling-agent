"""Database access for plans: threads, pending actions and questions (gateway_service, RLS).

Creating an action, moving its thread to "proposed" and writing the audit row happen in
one transaction: either all of it is recorded, or none. A second plan for the same task
hits the (user_id, task_id) unique constraint and creates nothing (E8).
"""

import json
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.expression import bindparam

from db.session import set_user_context
from google_gateway.events import write_audit
from shared import tracing
from shared.messages import Interval


@dataclass(frozen=True)
class OfferedReply:
    """What the last reply sent in a thread offered: the only times an event may use."""

    slots: tuple[Interval, ...]
    language: str
    duration_minutes: int


@dataclass(frozen=True)
class ThreadInfo:
    gmail_thread_id: str
    participants: tuple[str, ...]
    state: str


class ActionStore(Protocol):
    def thread(self, user_id: UUID, thread_id: UUID) -> ThreadInfo | None: ...

    def offered_reply(self, user_id: UUID, thread_id: UUID) -> OfferedReply | None: ...

    def end_of_workday(self, user_id: UUID) -> time: ...

    def replies_sent_in_thread(self, user_id: UUID, thread_id: UUID) -> int: ...

    def actions_since(self, user_id: UUID, since: datetime) -> int: ...

    def create_reply_action(
        self,
        user_id: UUID,
        thread_id: UUID,
        task_id: UUID,
        payload: dict[str, Any],
        content_hash: str,
        expires_at: datetime,
        kind: str = "reply_with_slots",
    ) -> UUID | None:
        """The new action's id, or None if this task already has one."""
        ...

    def create_question(
        self, user_id: UUID, thread_id: UUID, task_id: UUID, question: str
    ) -> bool: ...

    def close_thread(self, user_id: UUID, thread_id: UUID, reason: str) -> None: ...


_INSERT_ACTION = text(
    "INSERT INTO app.pending_actions"
    " (user_id, thread_id, task_id, kind, payload, content_hash, expires_at, trace_parent)"
    " VALUES (:user_id, :thread_id, :task_id, :kind, :payload, :hash, :expires, :trace)"
    " ON CONFLICT (user_id, task_id) DO NOTHING RETURNING action_id"
).bindparams(bindparam("payload", type_=JSONB))


class SqlActionStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def thread(self, user_id: UUID, thread_id: UUID) -> ThreadInfo | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            row = conn.execute(
                text(
                    "SELECT gmail_thread_id, participants, state FROM app.threads"
                    " WHERE user_id = :u AND thread_id = :t"
                ),
                {"u": user_id, "t": thread_id},
            ).one_or_none()
        return None if row is None else ThreadInfo(row[0], tuple(row[1]), row[2])

    def offered_reply(self, user_id: UUID, thread_id: UUID) -> OfferedReply | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            payload = conn.execute(
                text(
                    "SELECT payload FROM app.pending_actions"
                    " WHERE user_id = :u AND thread_id = :t AND kind = 'reply_with_slots'"
                    " AND status = 'executed' ORDER BY executed_at DESC LIMIT 1"
                ),
                {"u": user_id, "t": thread_id},
            ).scalar_one_or_none()
        if payload is None:
            return None
        return OfferedReply(
            slots=tuple(Interval.model_validate_json(json.dumps(s)) for s in payload["slots"]),
            language=str(payload["language"]),
            duration_minutes=int(payload["duration_minutes"]),
        )

    def end_of_workday(self, user_id: UUID) -> time:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            value = conn.execute(
                text("SELECT end_of_workday FROM app.settings WHERE user_id = :u"), {"u": user_id}
            ).scalar_one()
        return value  # type: ignore[no-any-return]

    def replies_sent_in_thread(self, user_id: UUID, thread_id: UUID) -> int:
        return self._count(
            user_id,
            "SELECT count(*) FROM app.pending_actions WHERE user_id = :u AND thread_id = :t"
            " AND kind = 'reply_with_slots' AND status = 'executed'",
            {"t": thread_id},
        )

    def actions_since(self, user_id: UUID, since: datetime) -> int:
        return self._count(
            user_id,
            "SELECT count(*) FROM app.pending_actions WHERE user_id = :u AND created_at >= :s",
            {"s": since},
        )

    def create_reply_action(
        self,
        user_id: UUID,
        thread_id: UUID,
        task_id: UUID,
        payload: dict[str, Any],
        content_hash: str,
        expires_at: datetime,
        kind: str = "reply_with_slots",
    ) -> UUID | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            action_id = conn.execute(
                _INSERT_ACTION,
                {
                    "user_id": user_id,
                    "thread_id": thread_id,
                    "task_id": task_id,
                    "payload": payload,
                    "hash": content_hash,
                    "expires": expires_at,
                    "kind": kind,
                    # The email's trace, continued by the executor after approval.
                    "trace": tracing.traceparent(),
                },
            ).scalar_one_or_none()
            if action_id is None:
                return None
            conn.execute(
                text(
                    "UPDATE app.threads SET state = 'proposed', updated_at = now()"
                    " WHERE user_id = :u AND thread_id = :t"
                ),
                {"u": user_id, "t": thread_id},
            )
            write_audit(
                conn,
                user_id,
                "pending_action_created",
                {"action_id": str(action_id), "content_hash": content_hash},
            )
        return UUID(str(action_id))

    def create_question(self, user_id: UUID, thread_id: UUID, task_id: UUID, question: str) -> bool:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            question_id = conn.execute(
                text(
                    "INSERT INTO app.user_questions (user_id, thread_id, task_id, question)"
                    " VALUES (:u, :t, :k, :q) ON CONFLICT (user_id, task_id) DO NOTHING"
                    " RETURNING question_id"
                ),
                {"u": user_id, "t": thread_id, "k": task_id, "q": question[:300]},
            ).scalar_one_or_none()
            if question_id is not None:
                write_audit(conn, user_id, "question_created", {"question_id": str(question_id)})
        return question_id is not None

    def close_thread(self, user_id: UUID, thread_id: UUID, reason: str) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                text(
                    "UPDATE app.threads SET state = 'closed', updated_at = now()"
                    " WHERE user_id = :u AND thread_id = :t AND state = 'open'"
                ),
                {"u": user_id, "t": thread_id},
            )
            write_audit(
                conn, user_id, "thread_closed", {"thread_id": str(thread_id), "reason": reason}
            )

    def _count(self, user_id: UUID, sql: str, params: dict[str, Any]) -> int:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            return int(conn.execute(text(sql), {"u": user_id, **params}).scalar_one())
