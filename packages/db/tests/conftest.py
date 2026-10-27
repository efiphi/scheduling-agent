"""Seed data for the database tests. The engine fixtures (owner, api, gateway) come from
db.testing, loaded by the root conftest.py."""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from db.session import set_user_context as as_user


@dataclass(frozen=True)
class Seed:
    user_a: UUID
    user_b: UUID
    action_a: UUID


@pytest.fixture
def seed(owner: Engine) -> Iterator[Seed]:
    """Two users with synthetic data; user A has one thread and one pending action."""
    user_a, user_b = uuid4(), uuid4()
    thread_a, action_a = uuid4(), uuid4()
    with owner.begin() as conn:
        for uid in (user_a, user_b):
            as_user(conn, uid)
            conn.execute(
                text("INSERT INTO app.users (user_id, email) VALUES (:id, :email)"),
                {"id": uid, "email": f"user-{uid}@example.com"},
            )
        as_user(conn, user_a)
        conn.execute(
            text(
                "INSERT INTO app.threads (thread_id, user_id, gmail_thread_id)"
                " VALUES (:t, :u, 'g-1')"
            ),
            {"t": thread_a, "u": user_a},
        )
        conn.execute(
            text(
                "INSERT INTO app.pending_actions"
                " (action_id, user_id, thread_id, kind, payload, content_hash, expires_at)"
                " VALUES (:a, :u, :t, 'reply_with_slots', '{}', 'sha256:test',"
                " now() + interval '1 day')"
            ),
            {"a": action_a, "u": user_a, "t": thread_a},
        )
        conn.execute(
            text(
                "INSERT INTO app.google_credentials"
                " (user_id, encrypted_refresh_token, key_version, scopes)"
                " VALUES (:u, '\\x00', 1, '{}')"
            ),
            {"u": user_a},
        )
    yield Seed(user_a, user_b, action_a)
    with owner.begin() as conn:
        for uid in (user_a, user_b):
            as_user(conn, uid)
            conn.execute(text("DELETE FROM app.users WHERE user_id = :id"), {"id": uid})
            conn.execute(text("DELETE FROM app.audit_log WHERE user_id = :id"), {"id": uid})
