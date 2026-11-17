"""SqlMailStore against the real database, as gateway_service (T13, T5, UC-M8)."""

from collections.abc import Iterator
from datetime import UTC, datetime, time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from google_gateway.mail_store import SqlMailStore

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


@pytest.fixture
def users(owner: Engine) -> Iterator[tuple[UUID, UUID]]:
    a, b = uuid4(), uuid4()
    with owner.begin() as conn:
        for uid in (a, b):
            conn.execute(
                text("INSERT INTO app.users (user_id, email) VALUES (:id, :email)"),
                {"id": uid, "email": f"user-{uid}@example.com"},
            )
            conn.execute(text("INSERT INTO app.settings (user_id) VALUES (:id)"), {"id": uid})
            conn.execute(
                text(
                    "INSERT INTO app.google_credentials"
                    " (user_id, encrypted_refresh_token, key_version, scopes)"
                    " VALUES (:id, '\\x00', 1, '{}')"
                ),
                {"id": uid},
            )
    yield a, b
    with owner.begin() as conn:
        for uid in (a, b):
            conn.execute(text("DELETE FROM app.users WHERE user_id = :id"), {"id": uid})
            for table in ("audit_log", "security_events"):
                conn.execute(text(f"DELETE FROM app.{table} WHERE user_id = :id"), {"id": uid})  # noqa: S608 - fixed table names


def test_connected_users_are_polled_until_the_token_is_rejected(
    gateway: Engine, users: tuple[UUID, UUID]
) -> None:
    a, b = users
    store = SqlMailStore(gateway)
    assert {a, b} <= set(store.users_to_poll())
    store.mark_expired(a)
    assert a not in store.users_to_poll()
    assert store.mailbox(a) is None


def test_history_id_round_trip(gateway: Engine, users: tuple[UUID, UUID]) -> None:
    a, _ = users
    store = SqlMailStore(gateway)
    box = store.mailbox(a)
    assert box is not None and box.history_id is None
    store.set_history_id(a, "12345")
    box = store.mailbox(a)
    assert box is not None and box.history_id == "12345"
    assert box.email == f"user-{a}@example.com"


def test_t5_thread_participants_accumulate(gateway: Engine, users: tuple[UUID, UUID]) -> None:
    a, _ = users
    store = SqlMailStore(gateway)
    first = store.upsert_thread(a, "g-thread", ["dana@example.org"])
    second = store.upsert_thread(a, "g-thread", ["bob@example.org", "dana@example.org"])
    assert first == second
    with gateway.begin() as conn:
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(a)})
        participants = conn.execute(
            text("SELECT participants FROM app.threads WHERE thread_id = :t"), {"t": first}
        ).scalar_one()
    assert participants == ["bob@example.org", "dana@example.org"]
    assert store.is_tracked_thread(a, "g-thread")


def test_t13_threads_are_per_user(gateway: Engine, users: tuple[UUID, UUID]) -> None:
    a, b = users
    store = SqlMailStore(gateway)
    store.upsert_thread(a, "g-shared-id", ["dana@example.org"])
    assert not store.is_tracked_thread(b, "g-shared-id")
    # The same Gmail thread id under another user is a separate thread.
    assert store.upsert_thread(b, "g-shared-id", []) != store.upsert_thread(a, "g-shared-id", [])


def test_skipped_email_keeps_three_fields_only(
    gateway: Engine, owner: Engine, users: tuple[UUID, UUID]
) -> None:
    a, _ = users
    SqlMailStore(gateway).record_skipped(a, "news@example.org", "x" * 600, NOW)
    with owner.begin() as conn:
        row = conn.execute(
            text("SELECT sender, subject, received_at FROM app.skipped_emails WHERE user_id = :a"),
            {"a": a},
        ).one()
    assert row[0] == "news@example.org"
    assert len(row[1]) == 500
    assert row[2] == NOW


def test_agent_context_comes_from_the_users_settings(
    gateway: Engine, users: tuple[UUID, UUID]
) -> None:
    a, _ = users
    context = SqlMailStore(gateway).agent_context(a, NOW)
    assert context.time_zone == "Asia/Jerusalem"
    assert context.work_days == (0, 1, 2, 3, 4)
    assert (context.work_start, context.work_end) == (time(9), time(18))
    assert context.now == NOW
