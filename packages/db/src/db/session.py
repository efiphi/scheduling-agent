"""The one place where a transaction learns which user it acts for (ADR-005, T13).

Row-Level Security policies (migration 0002) compare each row's user_id with this setting.
`is_local=true` scopes it to the current transaction, so a pooled connection can never
carry one request's user into the next.
"""

from uuid import UUID

from sqlalchemy import Connection, text


def set_user_context(conn: Connection, user_id: UUID) -> None:
    conn.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})
