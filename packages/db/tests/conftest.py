"""Fixtures for tests that run against a real Postgres with the roles and migrations applied.

Connection details come from the environment (the same variables as deploy/compose/.env).
Without them these tests are skipped locally; CI sets REQUIRE_DB=1 so a missing database
fails the run instead of silently skipping it.
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from db.session import set_user_context as as_user

HOST = os.environ.get("DB_HOST", "127.0.0.1")
PORT = os.environ.get("DB_PORT", "5432")
NAME = "scheduling_agent"

_PASSWORDS = {
    "scheduling_owner": "OWNER_DB_PASSWORD",
    "api_service": "API_DB_PASSWORD",
    "gateway_service": "GATEWAY_DB_PASSWORD",
}


def _engine(role: str) -> Engine:
    password = os.environ.get(_PASSWORDS[role])
    if not password:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(f"{_PASSWORDS[role]} is not set but REQUIRE_DB=1")
        pytest.skip("database tests need the role passwords in the environment")
    return create_engine(f"postgresql+psycopg://{role}:{password}@{HOST}:{PORT}/{NAME}")


@pytest.fixture(scope="session")
def owner() -> Engine:
    return _engine("scheduling_owner")


@pytest.fixture(scope="session")
def api() -> Engine:
    return _engine("api_service")


@pytest.fixture(scope="session")
def gateway() -> Engine:
    return _engine("gateway_service")


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
