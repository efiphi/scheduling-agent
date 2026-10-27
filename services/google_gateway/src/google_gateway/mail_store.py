"""The poller's database access, as the gateway_service role, one user per transaction (T13).

The role can read users and settings, read and update google_credentials and threads, and
append skipped_emails, audit_log and security_events (migration 0001).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Engine, text

from db.session import set_user_context
from google_gateway.events import write_audit, write_security_event
from google_gateway.token_crypto import EncryptedToken
from shared.messages import MAX_SUBJECT_CHARS, AgentContext


@dataclass(frozen=True)
class Mailbox:
    email: str
    token: EncryptedToken
    history_id: str | None


class MailStore(Protocol):
    def users_to_poll(self) -> list[UUID]: ...

    def mailbox(self, user_id: UUID) -> Mailbox | None: ...

    def set_history_id(self, user_id: UUID, history_id: str) -> None: ...

    def mark_expired(self, user_id: UUID) -> None: ...

    def is_tracked_thread(self, user_id: UUID, gmail_thread_id: str) -> bool: ...

    def upsert_thread(self, user_id: UUID, gmail_thread_id: str, participants: list[str]) -> UUID:
        """The thread's id; participants are added to the ones already known (T5)."""
        ...

    def record_skipped(
        self, user_id: UUID, sender: str, subject: str, received_at: datetime
    ) -> None: ...

    def agent_context(self, user_id: UUID, now: datetime) -> AgentContext: ...

    def audit(self, user_id: UUID, action: str, details: dict[str, Any]) -> None: ...

    def security_event(self, user_id: UUID, kind: str, details: dict[str, Any]) -> None: ...


# A thread the agent still coordinates. Closed or cancelled threads start over.
_TRACKED_STATES = ("open", "proposed", "scheduled")

_UPSERT_THREAD = text(
    "INSERT INTO app.threads (user_id, gmail_thread_id, participants)"
    " VALUES (:user_id, :gmail_thread_id, :participants)"
    " ON CONFLICT (user_id, gmail_thread_id) DO UPDATE SET"
    " participants = ARRAY(SELECT DISTINCT unnest(app.threads.participants"
    " || excluded.participants) ORDER BY 1),"
    " updated_at = now()"
    " RETURNING thread_id"
)


class SqlMailStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def users_to_poll(self) -> list[UUID]:
        # SECURITY DEFINER function (migration 0002): ids only, for active connected users.
        with self._engine.begin() as conn:
            return [
                UUID(str(r)) for r in conn.execute(text("SELECT app.users_to_poll()")).scalars()
            ]

    def mailbox(self, user_id: UUID) -> Mailbox | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            row = conn.execute(
                text(
                    "SELECT u.email, g.encrypted_refresh_token, g.key_version, g.gmail_history_id"
                    " FROM app.users AS u JOIN app.google_credentials AS g USING (user_id)"
                    " WHERE u.user_id = :id AND g.status = 'connected'"
                ),
                {"id": user_id},
            ).one_or_none()
        if row is None:
            return None
        return Mailbox(str(row[0]), EncryptedToken(bytes(row[1]), int(row[2])), row[3])

    def set_history_id(self, user_id: UUID, history_id: str) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                text("UPDATE app.google_credentials SET gmail_history_id = :h WHERE user_id = :id"),
                {"h": history_id, "id": user_id},
            )

    def mark_expired(self, user_id: UUID) -> None:
        """Google refused the token (revoked, or the 7-day testing-mode limit): E13."""
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                text(
                    "UPDATE app.google_credentials SET status = 'expired', updated_at = now()"
                    " WHERE user_id = :id"
                ),
                {"id": user_id},
            )
            write_security_event(conn, user_id, "google_token_rejected", {})

    def is_tracked_thread(self, user_id: UUID, gmail_thread_id: str) -> bool:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            found = conn.execute(
                text(
                    "SELECT 1 FROM app.threads"
                    " WHERE user_id = :id AND gmail_thread_id = :t AND state = ANY(:states)"
                ),
                {"id": user_id, "t": gmail_thread_id, "states": list(_TRACKED_STATES)},
            ).first()
        return found is not None

    def upsert_thread(self, user_id: UUID, gmail_thread_id: str, participants: list[str]) -> UUID:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            thread_id = conn.execute(
                _UPSERT_THREAD,
                {
                    "user_id": user_id,
                    "gmail_thread_id": gmail_thread_id,
                    "participants": participants,
                },
            ).scalar_one()
        return UUID(str(thread_id))

    def record_skipped(
        self, user_id: UUID, sender: str, subject: str, received_at: datetime
    ) -> None:
        # Sender, subject and time only, never the body (UC-M8). Deleted after 7 days.
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                text(
                    "INSERT INTO app.skipped_emails (user_id, sender, subject, received_at)"
                    " VALUES (:id, :sender, :subject, :at)"
                ),
                {
                    "id": user_id,
                    "sender": sender[:320],
                    "subject": subject[:MAX_SUBJECT_CHARS],
                    "at": received_at,
                },
            )

    def agent_context(self, user_id: UUID, now: datetime) -> AgentContext:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            row = conn.execute(
                text(
                    "SELECT time_zone, work_days, work_start, work_end,"
                    " default_duration_minutes, buffer_minutes"
                    " FROM app.settings WHERE user_id = :id"
                ),
                {"id": user_id},
            ).one()
        return AgentContext(
            time_zone=row[0],
            now=now,
            work_days=tuple(row[1]),
            work_start=row[2],
            work_end=row[3],
            default_duration_minutes=row[4],
            buffer_minutes=row[5],
        )

    def audit(self, user_id: UUID, action: str, details: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            write_audit(conn, user_id, action, details)

    def security_event(self, user_id: UUID, kind: str, details: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            write_security_event(conn, user_id, kind, details)
