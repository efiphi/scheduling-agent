"""The api's database access, as api_service, one user per transaction (RLS, T13).

The role reads users, settings, threads, pending actions and questions; it may only change
an action's status and decision time (never its payload or hash, T3), insert approvals,
and mark questions answered (migrations 0001, 0004).

Approving is one transaction:
1. Lock the action row (FOR UPDATE), so two approval requests cannot both pass the checks.
2. It must be pending, not expired, and its content hash must equal the hash the user saw.
3. Insert the approval record: single use, bound to the action and the hash. The
   database's one-approval-per-action constraint rejects a second approval (T10).
4. Mark the action approved, and write the audit row.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Engine, text

from db.session import set_user_context


class ApproveResult(StrEnum):
    APPROVED = "approved"
    NOT_FOUND = "not_found"
    NOT_PENDING = "not_pending"
    EXPIRED = "expired"
    HASH_MISMATCH = "hash_mismatch"


@dataclass(frozen=True)
class User:
    user_id: UUID
    email: str
    status: str
    is_admin: bool


@dataclass(frozen=True)
class Action:
    action_id: UUID
    kind: str
    status: str
    payload: dict[str, Any]
    content_hash: str
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class Question:
    question_id: UUID
    question: str
    created_at: datetime


class ApiStore(Protocol):
    def find_user(self, email: str) -> UUID | None: ...

    def user(self, user_id: UUID) -> User | None: ...

    def actions(self, user_id: UUID, status: str) -> list[Action]: ...

    def action(self, user_id: UUID, action_id: UUID) -> Action | None: ...

    def approve(self, user_id: UUID, action_id: UUID, content_hash: str) -> ApproveResult: ...

    def reject(self, user_id: UUID, action_id: UUID) -> bool: ...

    def questions(self, user_id: UUID) -> list[Question]: ...

    def dismiss_question(self, user_id: UUID, question_id: UUID) -> bool: ...

    def audit(self, user_id: UUID, action: str, details: dict[str, Any]) -> None: ...


_ACTION_COLUMNS = "action_id, kind, status, payload, content_hash, expires_at, created_at"


def _action(row: Any) -> Action:
    return Action(UUID(str(row[0])), row[1], row[2], dict(row[3]), row[4], row[5], row[6])


def _audit(conn: Any, user_id: UUID, action: str, details: dict[str, Any]) -> None:
    conn.execute(
        text(
            "INSERT INTO app.audit_log (user_id, actor, action, details)"
            " VALUES (:u, 'api', :a, CAST(:d AS jsonb))"
        ),
        {"u": user_id, "a": action, "d": json.dumps(details)},
    )


class SqlApiStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def find_user(self, email: str) -> UUID | None:
        # SECURITY DEFINER function (migration 0002): returns an id or nothing, before login.
        with self._engine.begin() as conn:
            found = conn.execute(
                text("SELECT app.find_user_by_email(:e)"), {"e": email}
            ).scalar_one_or_none()
        return None if found is None else UUID(str(found))

    def user(self, user_id: UUID) -> User | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            row = conn.execute(
                text("SELECT user_id, email, status, is_admin FROM app.users WHERE user_id = :u"),
                {"u": user_id},
            ).one_or_none()
        return None if row is None else User(UUID(str(row[0])), row[1], row[2], row[3])

    def actions(self, user_id: UUID, status: str) -> list[Action]:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            rows = conn.execute(
                text(
                    f"SELECT {_ACTION_COLUMNS} FROM app.pending_actions"  # noqa: S608 - fixed columns
                    " WHERE user_id = :u AND status = :s ORDER BY expires_at, created_at"
                ),
                {"u": user_id, "s": status},
            ).all()
        return [_action(r) for r in rows]

    def action(self, user_id: UUID, action_id: UUID) -> Action | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            row = conn.execute(
                text(
                    f"SELECT {_ACTION_COLUMNS} FROM app.pending_actions"  # noqa: S608 - fixed columns
                    " WHERE user_id = :u AND action_id = :a"
                ),
                {"u": user_id, "a": action_id},
            ).one_or_none()
        return None if row is None else _action(row)

    def approve(self, user_id: UUID, action_id: UUID, content_hash: str) -> ApproveResult:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            row = conn.execute(
                text(
                    "SELECT status, content_hash, expires_at <= now() FROM app.pending_actions"
                    " WHERE user_id = :u AND action_id = :a FOR UPDATE"
                ),
                {"u": user_id, "a": action_id},
            ).one_or_none()
            if row is None:
                return ApproveResult.NOT_FOUND
            status, stored_hash, expired = row
            if status != "pending":
                return ApproveResult.NOT_PENDING
            if expired:
                return ApproveResult.EXPIRED
            if stored_hash != content_hash:
                return ApproveResult.HASH_MISMATCH
            conn.execute(
                text(
                    "INSERT INTO app.approvals (user_id, action_id, content_hash, channel)"
                    " VALUES (:u, :a, :h, 'web')"
                ),
                {"u": user_id, "a": action_id, "h": content_hash},
            )
            conn.execute(
                text(
                    "UPDATE app.pending_actions SET status = 'approved', decided_at = now()"
                    " WHERE user_id = :u AND action_id = :a"
                ),
                {"u": user_id, "a": action_id},
            )
            _audit(
                conn, user_id, "action_approved", {"action_id": str(action_id), "channel": "web"}
            )
        return ApproveResult.APPROVED

    def reject(self, user_id: UUID, action_id: UUID) -> bool:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            changed = conn.execute(
                text(
                    "UPDATE app.pending_actions SET status = 'rejected', decided_at = now()"
                    " WHERE user_id = :u AND action_id = :a AND status = 'pending'"
                ),
                {"u": user_id, "a": action_id},
            ).rowcount
            if changed:
                _audit(conn, user_id, "action_rejected", {"action_id": str(action_id)})
        return bool(changed)

    def questions(self, user_id: UUID) -> list[Question]:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            rows = conn.execute(
                text(
                    "SELECT question_id, question, created_at FROM app.user_questions"
                    " WHERE user_id = :u AND status = 'open' ORDER BY created_at DESC"
                ),
                {"u": user_id},
            ).all()
        return [Question(UUID(str(r[0])), r[1], r[2]) for r in rows]

    def dismiss_question(self, user_id: UUID, question_id: UUID) -> bool:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            changed = conn.execute(
                text(
                    "UPDATE app.user_questions SET status = 'dismissed', answered_at = now()"
                    " WHERE user_id = :u AND question_id = :q AND status = 'open'"
                ),
                {"u": user_id, "q": question_id},
            ).rowcount
        return bool(changed)

    def audit(self, user_id: UUID, action: str, details: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            _audit(conn, user_id, action, details)
