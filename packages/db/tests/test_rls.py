"""Row-Level Security: a service acting for one user never sees or touches another's rows (T13).

Every test logs in as a real service role. "User B" is the attacker's context; user A owns
the data. Postgres itself must filter or refuse, whatever the application code asks for.
"""

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from db.session import set_user_context

pytestmark = pytest.mark.db

RLS_VIOLATION = "row-level security policy"


@pytest.fixture
def full_seed(owner: Engine, seed: Any) -> Iterator[Any]:
    """User A also gets settings, an approval, a skipped email, a question, an audit row and
    a security event."""
    with owner.begin() as conn:
        set_user_context(conn, seed.user_a)
        params = {"u": seed.user_a, "a": seed.action_a}
        conn.execute(text("INSERT INTO app.settings (user_id) VALUES (:u)"), params)
        conn.execute(
            text(
                "INSERT INTO app.approvals (user_id, action_id, content_hash, channel)"
                " VALUES (:u, :a, 'sha256:test', 'web')"
            ),
            params,
        )
        conn.execute(
            text(
                "INSERT INTO app.skipped_emails (user_id, sender, subject, received_at)"
                " VALUES (:u, 'news@example.com', 'Newsletter', now())"
            ),
            params,
        )
        conn.execute(
            text("INSERT INTO app.user_questions (user_id, question) VALUES (:u, 'When?')"),
            params,
        )
        conn.execute(
            text("INSERT INTO app.audit_log (user_id, actor, action) VALUES (:u, 'api', 'seed')"),
            params,
        )
        conn.execute(
            text("INSERT INTO app.security_events (user_id, kind) VALUES (:u, 'seed')"), params
        )
    yield seed


def count(engine: Engine, context: UUID | None, table: str, owner_id: UUID) -> int:
    with engine.begin() as conn:
        if context is not None:
            set_user_context(conn, context)
        # Table names come from the fixed lists below, never from input.
        sql = text(f"SELECT count(*) FROM app.{table} WHERE user_id = :owner")  # noqa: S608
        return int(conn.execute(sql, {"owner": owner_id}).scalar_one())


# Tables each role may read (migrations 0001 and 0004).
API_READABLE = [
    "user_questions",
    "users",
    "settings",
    "threads",
    "pending_actions",
    "approvals",
    "audit_log",
    "skipped_emails",
    "security_events",
]
GATEWAY_READABLE = [
    "user_questions",
    "users",
    "settings",
    "google_credentials",
    "threads",
    "pending_actions",
    "approvals",
    "audit_log",
    "skipped_emails",
]


# --- Reading ----------------------------------------------------------------------------


@pytest.mark.parametrize("table", API_READABLE)
def test_t13_api_sees_own_rows(api: Engine, full_seed: Any, table: str) -> None:
    assert count(api, full_seed.user_a, table, full_seed.user_a) >= 1


@pytest.mark.parametrize("table", API_READABLE)
def test_t13_api_cannot_read_another_users_rows(api: Engine, full_seed: Any, table: str) -> None:
    assert count(api, full_seed.user_b, table, full_seed.user_a) == 0


@pytest.mark.parametrize("table", GATEWAY_READABLE)
def test_t13_gateway_cannot_read_another_users_rows(
    gateway: Engine, full_seed: Any, table: str
) -> None:
    assert count(gateway, full_seed.user_b, table, full_seed.user_a) == 0


@pytest.mark.parametrize("table", ["users", "pending_actions", "threads", "audit_log"])
def test_t13_no_user_context_means_no_rows(api: Engine, full_seed: Any, table: str) -> None:
    # A forgotten set_user_context fails closed: nothing, not everything.
    assert count(api, None, table, full_seed.user_a) == 0


def test_t13_context_does_not_leak_between_transactions(api: Engine, full_seed: Any) -> None:
    # set_config(..., is_local=true): the user lives only as long as one transaction,
    # so a reused (pooled) connection never carries one request's user into the next.
    with api.connect() as conn:
        with conn.begin():
            set_user_context(conn, full_seed.user_a)
        with conn.begin():
            leaked = conn.execute(text("SELECT count(*) FROM app.pending_actions")).scalar_one()
    assert leaked == 0


# --- Writing ----------------------------------------------------------------------------


def test_t13_cannot_update_another_users_action(api: Engine, full_seed: Any) -> None:
    with api.begin() as conn:
        set_user_context(conn, full_seed.user_b)
        updated = conn.execute(
            text("UPDATE app.pending_actions SET status = 'rejected' WHERE action_id = :a"),
            {"a": full_seed.action_a},
        ).rowcount
    assert updated == 0


def test_t13_cannot_write_rows_for_another_user(api: Engine, full_seed: Any) -> None:
    with pytest.raises(ProgrammingError, match=RLS_VIOLATION), api.begin() as conn:
        set_user_context(conn, full_seed.user_b)
        conn.execute(
            text("INSERT INTO app.audit_log (user_id, actor, action) VALUES (:u, 'api', 'forged')"),
            {"u": full_seed.user_a},
        )


def test_t13_cannot_create_a_user_under_another_context(api: Engine, full_seed: Any) -> None:
    with pytest.raises(ProgrammingError, match=RLS_VIOLATION), api.begin() as conn:
        set_user_context(conn, full_seed.user_b)
        conn.execute(
            text("INSERT INTO app.users (user_id, email) VALUES (gen_random_uuid(), :e)"),
            {"e": "someone-else@example.com"},
        )


def test_security_event_without_a_user_can_be_written_but_not_read(
    gateway: Engine, api: Engine, full_seed: Any
) -> None:
    # A message from an unknown number belongs to no user (T8): recorded, visible to no service.
    with gateway.begin() as conn:
        conn.execute(text("INSERT INTO app.security_events (kind) VALUES ('unknown_sender_test')"))
    with api.begin() as conn:
        set_user_context(conn, full_seed.user_a)
        visible = conn.execute(
            text("SELECT count(*) FROM app.security_events WHERE kind = 'unknown_sender_test'")
        ).scalar_one()
    assert visible == 0


# --- The two controlled exceptions ------------------------------------------------------


def _email(user_id: UUID) -> str:
    return f"user-{user_id}@example.com"


def test_find_user_by_email_returns_only_an_id(api: Engine, full_seed: Any) -> None:
    with api.begin() as conn:  # no user context yet: this is the login step
        row = conn.execute(
            text("SELECT * FROM app.find_user_by_email(:e)"),
            {"e": _email(full_seed.user_a).upper()},
        ).one()
    assert tuple(row) == (full_seed.user_a,)  # one column, the id; email matched case-insensitively


def test_find_user_by_email_unknown_address(api: Engine, full_seed: Any) -> None:
    with api.begin() as conn:
        found = conn.execute(
            text("SELECT app.find_user_by_email('nobody@example.com')")
        ).scalar_one()
    assert found is None


def test_users_to_poll_lists_only_connected_active_users(gateway: Engine, full_seed: Any) -> None:
    with gateway.begin() as conn:
        polled = set(conn.execute(text("SELECT * FROM app.users_to_poll()")).scalars())
    assert full_seed.user_a in polled  # has Google credentials
    assert full_seed.user_b not in polled  # does not


def test_users_to_poll_skips_a_paused_user(gateway: Engine, owner: Engine, full_seed: Any) -> None:
    with owner.begin() as conn:  # paused by the stop code or the web pause button (ADR-014)
        conn.execute(
            text("UPDATE app.users SET status = 'paused' WHERE user_id = :u"),
            {"u": full_seed.user_a},
        )
    with gateway.begin() as conn:
        polled = set(conn.execute(text("SELECT * FROM app.users_to_poll()")).scalars())
    assert full_seed.user_a not in polled


def test_gateway_cannot_call_find_user_by_email(gateway: Engine, full_seed: Any) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"), gateway.begin() as conn:
        conn.execute(text("SELECT app.find_user_by_email('x@example.com')"))


def test_api_cannot_call_users_to_poll(api: Engine, full_seed: Any) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"), api.begin() as conn:
        conn.execute(text("SELECT * FROM app.users_to_poll()"))
