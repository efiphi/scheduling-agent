"""google-gateway's database access for the connect flow, as the gateway_service role.

Every query that touches a user's rows first sets the user context, so Row-Level Security
limits the transaction to that user (ADR-005, T13). The role can read users, write
google_credentials, and append to audit_log and security_events, nothing more (migration 0001).
"""

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.expression import bindparam

from db.session import set_user_context
from google_gateway.token_crypto import EncryptedToken


class CredentialRepository(Protocol):
    def user_email(self, user_id: UUID) -> str | None: ...

    def save_credentials(self, user_id: UUID, token: EncryptedToken, scopes: list[str]) -> None:
        """Store the encrypted token and its audit row in one transaction."""
        ...

    def load_credentials(self, user_id: UUID) -> tuple[EncryptedToken, list[str]] | None: ...

    def audit(self, user_id: UUID, action: str, details: dict[str, Any]) -> None: ...

    def security_event(self, user_id: UUID | None, kind: str, details: dict[str, Any]) -> None: ...


_AUDIT = text(
    "INSERT INTO app.audit_log (user_id, actor, action, details)"
    " VALUES (:user_id, 'gateway', :action, :details)"
).bindparams(bindparam("details", type_=JSONB))

_SECURITY_EVENT = text(
    "INSERT INTO app.security_events (user_id, kind, details) VALUES (:user_id, :kind, :details)"
).bindparams(bindparam("details", type_=JSONB))

# A reconnect replaces the old token: the newest consent is the one that counts.
_UPSERT = text(
    "INSERT INTO app.google_credentials"
    " (user_id, encrypted_refresh_token, key_version, scopes, status)"
    " VALUES (:user_id, :data, :key_version, :scopes, 'connected')"
    " ON CONFLICT (user_id) DO UPDATE SET"
    " encrypted_refresh_token = excluded.encrypted_refresh_token,"
    " key_version = excluded.key_version, scopes = excluded.scopes,"
    " status = 'connected', updated_at = now()"
)


class SqlCredentialRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def user_email(self, user_id: UUID) -> str | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            email = conn.execute(
                text("SELECT email FROM app.users WHERE user_id = :id"), {"id": user_id}
            ).scalar_one_or_none()
        return None if email is None else str(email)

    def save_credentials(self, user_id: UUID, token: EncryptedToken, scopes: list[str]) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(
                _UPSERT,
                {
                    "user_id": user_id,
                    "data": token.data,
                    "key_version": token.key_version,
                    "scopes": scopes,
                },
            )
            conn.execute(
                _AUDIT,
                {"user_id": user_id, "action": "google_connected", "details": {"scopes": scopes}},
            )

    def load_credentials(self, user_id: UUID) -> tuple[EncryptedToken, list[str]] | None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            row = conn.execute(
                text(
                    "SELECT encrypted_refresh_token, key_version, scopes"
                    " FROM app.google_credentials WHERE user_id = :id AND status = 'connected'"
                ),
                {"id": user_id},
            ).one_or_none()
        if row is None:
            return None
        return EncryptedToken(bytes(row[0]), row[1]), list(row[2])

    def audit(self, user_id: UUID, action: str, details: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            set_user_context(conn, user_id)
            conn.execute(_AUDIT, {"user_id": user_id, "action": action, "details": details})

    def security_event(self, user_id: UUID | None, kind: str, details: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            if user_id is not None:
                set_user_context(conn, user_id)
            conn.execute(_SECURITY_EVENT, {"user_id": user_id, "kind": kind, "details": details})
