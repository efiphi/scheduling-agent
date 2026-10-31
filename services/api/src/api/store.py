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
from sqlalchemy.exc import IntegrityError

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

    # --- WhatsApp (step 1b) ----------------------------------------------------------

    def whatsapp_senders(self, number: str) -> list[tuple[UUID, str]]:
        """(user_id, "owner" | "backup") for every user this number belongs to."""
        ...

    def stop_code_hash(self, user_id: UUID) -> str | None: ...

    def whatsapp_verified(self, user_id: UUID) -> bool: ...

    def set_stop_code_hash(self, user_id: UUID, code_hash: str) -> None: ...

    def bind_whatsapp_number(self, user_id: UUID, number: str) -> bool:
        """False if the number already belongs to another user."""
        ...

    def backup_numbers(self, user_id: UUID) -> list[str]: ...

    def set_backup_numbers(self, user_id: UUID, numbers: list[str]) -> None: ...

    def pause(self, user_id: UUID, channel: str) -> int:
        """Pause the agent and cancel every pending action; returns how many (ADR-014)."""
        ...

    def resume(self, user_id: UUID) -> None: ...

    def security_event(self, user_id: UUID | None, kind: str, details: dict[str, Any]) -> None: ...


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

    # --- WhatsApp ----------------------------------------------------------------------

    def whatsapp_senders(self, number: str) -> list[tuple[UUID, str]]:
        # SECURITY DEFINER (migration 0005): a webhook has a number, not yet a user.
        with self._engine.begin() as conn:
            rows = conn.execute(
                text("SELECT user_id, role FROM app.whatsapp_senders(:n)"), {"n": number}
            ).all()
        return [(UUID(str(r[0])), str(r[1])) for r in rows]

    def stop_code_hash(self, user_id: UUID) -> str | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            value = conn.execute(
                text("SELECT stop_code_hash FROM app.users WHERE user_id = :u"), {"u": user_id}
            ).scalar_one_or_none()
        return None if value is None else str(value)

    def whatsapp_verified(self, user_id: UUID) -> bool:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            number = conn.execute(
                text("SELECT whatsapp_number FROM app.users WHERE user_id = :u"), {"u": user_id}
            ).scalar_one_or_none()
        return number is not None

    def set_stop_code_hash(self, user_id: UUID, code_hash: str) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                text("UPDATE app.users SET stop_code_hash = :h WHERE user_id = :u"),
                {"h": code_hash, "u": user_id},
            )
            _audit(conn, user_id, "stop_code_changed", {})

    def bind_whatsapp_number(self, user_id: UUID, number: str) -> bool:
        try:
            with self._engine.begin() as conn:
                set_user_context(conn, user_id)
                conn.execute(
                    text("UPDATE app.users SET whatsapp_number = :n WHERE user_id = :u"),
                    {"n": number, "u": user_id},
                )
                _audit(conn, user_id, "whatsapp_number_verified", {})
        except IntegrityError:
            return False  # unique: the number is already another user's
        return True

    def backup_numbers(self, user_id: UUID) -> list[str]:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            rows = conn.execute(
                text("SELECT number FROM app.backup_numbers WHERE user_id = :u ORDER BY number"),
                {"u": user_id},
            ).scalars()
            return [str(r) for r in rows]

    def set_backup_numbers(self, user_id: UUID, numbers: list[str]) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(text("DELETE FROM app.backup_numbers WHERE user_id = :u"), {"u": user_id})
            for number in numbers:
                conn.execute(
                    text("INSERT INTO app.backup_numbers (user_id, number) VALUES (:u, :n)"),
                    {"u": user_id, "n": number},
                )
            _audit(conn, user_id, "backup_numbers_changed", {"count": len(numbers)})

    def pause(self, user_id: UUID, channel: str) -> int:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                text("UPDATE app.users SET status = 'paused' WHERE user_id = :u"), {"u": user_id}
            )
            cancelled = conn.execute(
                text(
                    "UPDATE app.pending_actions SET status = 'rejected', decided_at = now()"
                    " WHERE user_id = :u AND status IN ('pending', 'approved')"
                ),
                {"u": user_id},
            ).rowcount
            _audit(conn, user_id, "agent_paused", {"channel": channel, "cancelled": cancelled})
        return int(cancelled)

    def resume(self, user_id: UUID) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                text("UPDATE app.users SET status = 'active' WHERE user_id = :u"), {"u": user_id}
            )
            _audit(conn, user_id, "agent_resumed", {"channel": "web"})

    def security_event(self, user_id: UUID | None, kind: str, details: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            if user_id is not None:
                set_user_context(conn, user_id)
            conn.execute(
                text(
                    "INSERT INTO app.security_events (user_id, kind, details)"
                    " VALUES (:u, :k, CAST(:d AS jsonb))"
                ),
                {"u": user_id, "k": kind, "d": json.dumps(details)},
            )
