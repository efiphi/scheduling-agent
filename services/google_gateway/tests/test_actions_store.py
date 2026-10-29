"""SqlActionStore against the real database (invariant 4, E8, T13)."""

from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from google_gateway.actions_store import SqlActionStore
from google_gateway.mail_store import SqlMailStore

pytestmark = pytest.mark.db

PAYLOAD = {"to": ["dana@example.org"], "body": "Hi"}
EXPIRES = datetime(2026, 11, 2, 16, 0, tzinfo=UTC)


@pytest.fixture
def user_thread(owner: Engine, gateway: Engine) -> Iterator[tuple[UUID, UUID]]:
    user = uuid4()
    with owner.begin() as conn:
        conn.execute(
            text("INSERT INTO app.users (user_id, email) VALUES (:id, :email)"),
            {"id": user, "email": f"user-{user}@example.com"},
        )
        conn.execute(text("INSERT INTO app.settings (user_id) VALUES (:id)"), {"id": user})
    thread = SqlMailStore(gateway).upsert_thread(user, "g-thread", ["dana@example.org"])
    yield user, thread
    with owner.begin() as conn:
        conn.execute(text("DELETE FROM app.users WHERE user_id = :id"), {"id": user})
        conn.execute(text("DELETE FROM app.audit_log WHERE user_id = :id"), {"id": user})


def test_action_thread_state_and_audit_in_one_go(
    gateway: Engine, owner: Engine, user_thread: tuple[UUID, UUID]
) -> None:
    user, thread = user_thread
    store = SqlActionStore(gateway)
    action = store.create_reply_action(user, thread, uuid4(), PAYLOAD, "sha256:abc", EXPIRES)
    assert action is not None
    assert store.thread(user, thread).state == "proposed"  # type: ignore[union-attr]
    with owner.begin() as conn:
        row = conn.execute(
            text(
                "SELECT payload, content_hash, status FROM app.pending_actions WHERE action_id = :a"
            ),
            {"a": action},
        ).one()
        audit = conn.execute(
            text(
                "SELECT details->>'content_hash' FROM app.audit_log"
                " WHERE user_id = :u AND action = 'pending_action_created'"
            ),
            {"u": user},
        ).scalar_one()
    assert row == (PAYLOAD, "sha256:abc", "pending")
    assert audit == "sha256:abc"


def test_e8_one_action_per_task_enforced_by_the_database(
    gateway: Engine, user_thread: tuple[UUID, UUID]
) -> None:
    user, thread = user_thread
    store, task = SqlActionStore(gateway), uuid4()
    assert store.create_reply_action(user, thread, task, PAYLOAD, "sha256:a", EXPIRES)
    assert store.create_reply_action(user, thread, task, PAYLOAD, "sha256:b", EXPIRES) is None
    assert store.actions_since(user, datetime.now(UTC) - timedelta(days=1)) == 1


def test_questions_are_deduplicated_too(gateway: Engine, user_thread: tuple[UUID, UUID]) -> None:
    user, thread = user_thread
    store, task = SqlActionStore(gateway), uuid4()
    assert store.create_question(user, thread, task, "When?")
    assert not store.create_question(user, thread, task, "When?")


def test_t13_another_user_cannot_see_the_thread(
    gateway: Engine, owner: Engine, user_thread: tuple[UUID, UUID]
) -> None:
    _, thread = user_thread
    assert SqlActionStore(gateway).thread(uuid4(), thread) is None


def test_settings_and_closing(gateway: Engine, user_thread: tuple[UUID, UUID]) -> None:
    user, thread = user_thread
    store = SqlActionStore(gateway)
    assert store.end_of_workday(user) == time(18)
    store.close_thread(user, thread, "not_a_meeting_request")
    assert store.thread(user, thread).state == "closed"  # type: ignore[union-attr]
    assert store.replies_sent_in_thread(user, thread) == 0
