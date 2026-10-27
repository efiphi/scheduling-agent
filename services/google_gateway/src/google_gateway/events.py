"""Writing audit and security rows, inside a caller's transaction (T22: ids and outcomes only)."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.expression import bindparam

_AUDIT = text(
    "INSERT INTO app.audit_log (user_id, actor, action, details)"
    " VALUES (:user_id, 'gateway', :action, :details)"
).bindparams(bindparam("details", type_=JSONB))

_SECURITY_EVENT = text(
    "INSERT INTO app.security_events (user_id, kind, details) VALUES (:user_id, :kind, :details)"
).bindparams(bindparam("details", type_=JSONB))


def write_audit(conn: Connection, user_id: UUID, action: str, details: dict[str, Any]) -> None:
    conn.execute(_AUDIT, {"user_id": user_id, "action": action, "details": details})


def write_security_event(
    conn: Connection, user_id: UUID | None, kind: str, details: dict[str, Any]
) -> None:
    conn.execute(_SECURITY_EVENT, {"user_id": user_id, "kind": kind, "details": details})
