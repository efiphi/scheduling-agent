"""Each service can touch only the tables and columns migration 0001 grants it (invariant 7).

Every test connects as a real service role and tries something; the "cannot" tests are
attacks that Postgres itself must refuse, whatever the application code does.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from db.session import set_user_context as as_user

pytestmark = pytest.mark.db

DENIED = "permission denied"


def run(engine: Engine, user: UUID, sql: str, **params: object) -> int:
    with engine.begin() as conn:
        as_user(conn, user)
        return conn.execute(text(sql), params).rowcount


# --- Google tokens: google-gateway only (invariant 1) ------------------------------------


def test_t16_api_cannot_read_google_credentials(api: Engine, seed: Any) -> None:
    with pytest.raises(ProgrammingError, match=DENIED):
        run(api, seed.user_a, "SELECT encrypted_refresh_token FROM app.google_credentials")


def test_gateway_can_read_google_credentials(gateway: Engine, seed: Any) -> None:
    assert (
        run(
            gateway,
            seed.user_a,
            "SELECT 1 FROM app.google_credentials WHERE user_id = :u",
            u=seed.user_a,
        )
        == 1
    )


# --- Pending actions: content and hash are written once (T3) ------------------------------


# Full statements, not built from strings: the tests model a tampering attempt per column.
TAMPER = {
    "payload": 'UPDATE app.pending_actions SET payload = \'{"to": "x"}\' WHERE action_id = :a',
    "content_hash": "UPDATE app.pending_actions SET content_hash = 'forged' WHERE action_id = :a",
    "expires_at": "UPDATE app.pending_actions SET expires_at = 'infinity' WHERE action_id = :a",
    "user_id": "UPDATE app.pending_actions SET user_id = user_id WHERE action_id = :a",
}


@pytest.mark.parametrize("column", ["payload", "content_hash", "expires_at", "user_id"])
def test_t3_api_cannot_change_what_was_proposed(api: Engine, seed: Any, column: str) -> None:
    with pytest.raises(ProgrammingError, match=DENIED):
        run(api, seed.user_a, TAMPER[column], a=seed.action_a)


@pytest.mark.parametrize("column", ["payload", "content_hash"])
def test_t3_gateway_cannot_change_what_was_proposed(
    gateway: Engine, seed: Any, column: str
) -> None:
    with pytest.raises(ProgrammingError, match=DENIED):
        run(gateway, seed.user_a, TAMPER[column], a=seed.action_a)


def test_api_can_record_a_rejection(api: Engine, seed: Any) -> None:
    updated = run(
        api,
        seed.user_a,
        "UPDATE app.pending_actions SET status = 'rejected', decided_at = now()"
        " WHERE action_id = :a",
        a=seed.action_a,
    )
    assert updated == 1


def test_api_cannot_create_pending_actions(api: Engine, seed: Any) -> None:
    # Only the gateway creates actions, after the policy guard.
    with pytest.raises(ProgrammingError, match=DENIED):
        run(
            api,
            seed.user_a,
            "INSERT INTO app.pending_actions (user_id, kind, payload, content_hash, expires_at)"
            " VALUES (:u, 'block_time', '{}', 'x', now())",
            u=seed.user_a,
        )


def test_a_pending_action_can_carry_its_trace_and_nothing_else(gateway: Engine, seed: Any) -> None:
    # Migration 0006: the column accepts a W3C traceparent only, so it cannot become a
    # place to stash email content or anything else.
    insert = (
        "INSERT INTO app.pending_actions"
        " (user_id, kind, payload, content_hash, expires_at, trace_parent)"
        " VALUES (:u, 'block_time', '{}', 'x', now() + interval '1 hour', :t)"
    )
    good = "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01"
    assert run(gateway, seed.user_a, insert, u=seed.user_a, t=good) == 1
    for bad in ("Meeting with Dana tomorrow", good.upper(), good + " ", "01" + good[2:]):
        with pytest.raises(IntegrityError, match="pending_actions_trace_parent_format"):
            run(gateway, seed.user_a, insert, u=seed.user_a, t=bad)


@pytest.mark.parametrize("role", ["api", "gateway"])
def test_no_service_can_delete_actions(
    role: str, seed: Any, request: pytest.FixtureRequest
) -> None:
    engine: Engine = request.getfixturevalue(role)
    with pytest.raises(ProgrammingError, match=DENIED):
        run(
            engine,
            seed.user_a,
            "DELETE FROM app.pending_actions WHERE action_id = :a",
            a=seed.action_a,
        )


# --- Approvals: single use, bound to the user's own action (invariant 4) ------------------


def _approve(api: Engine, user: UUID, action: UUID) -> None:
    run(
        api,
        user,
        "INSERT INTO app.approvals (user_id, action_id, content_hash, channel)"
        " VALUES (:u, :a, 'sha256:test', 'web')",
        u=user,
        a=action,
    )


def test_t10_an_action_can_be_approved_only_once(api: Engine, seed: Any) -> None:
    _approve(api, seed.user_a, seed.action_a)
    with pytest.raises(IntegrityError, match="approvals_one_per_action"):
        _approve(api, seed.user_a, seed.action_a)


def test_t13_cannot_approve_another_users_action(api: Engine, seed: Any) -> None:
    # User B tries to attach an approval to user A's action.
    with pytest.raises(IntegrityError, match="approvals_action_same_user"):
        _approve(api, seed.user_b, seed.action_a)


def test_gateway_can_only_mark_an_approval_used(gateway: Engine, api: Engine, seed: Any) -> None:
    _approve(api, seed.user_a, seed.action_a)
    assert (
        run(
            gateway,
            seed.user_a,
            "UPDATE app.approvals SET used_at = now() WHERE action_id = :a",
            a=seed.action_a,
        )
        == 1
    )
    with pytest.raises(ProgrammingError, match=DENIED):
        run(
            gateway,
            seed.user_a,
            "UPDATE app.approvals SET content_hash = 'forged' WHERE action_id = :a",
            a=seed.action_a,
        )


# --- Audit log: append-only for everyone --------------------------------------------------


@pytest.mark.parametrize("role", ["api", "gateway"])
def test_audit_log_is_append_only(role: str, seed: Any, request: pytest.FixtureRequest) -> None:
    engine: Engine = request.getfixturevalue(role)
    actor = "api" if role == "api" else "gateway"
    run(
        engine,
        seed.user_a,
        "INSERT INTO app.audit_log (user_id, actor, action) VALUES (:u, :actor, 'test')",
        u=seed.user_a,
        actor=actor,
    )
    with pytest.raises(ProgrammingError, match=DENIED):
        run(
            engine,
            seed.user_a,
            "UPDATE app.audit_log SET action = 'covered up' WHERE user_id = :u",
            u=seed.user_a,
        )
    with pytest.raises(ProgrammingError, match=DENIED):
        run(engine, seed.user_a, "DELETE FROM app.audit_log WHERE user_id = :u", u=seed.user_a)


# --- Users and settings ------------------------------------------------------------------


def test_gateway_cannot_create_users(gateway: Engine, seed: Any) -> None:
    with pytest.raises(ProgrammingError, match=DENIED):
        run(gateway, seed.user_a, "INSERT INTO app.users (email) VALUES ('intruder@example.com')")


def test_api_cannot_make_a_user_admin(api: Engine, seed: Any) -> None:
    # is_admin is not in api's column grant: no privilege escalation through the web API.
    with pytest.raises(ProgrammingError, match=DENIED):
        run(
            api,
            seed.user_a,
            "UPDATE app.users SET is_admin = true WHERE user_id = :u",
            u=seed.user_a,
        )


def test_gateway_cannot_change_settings(gateway: Engine, seed: Any) -> None:
    # Settings change only from the verified owner, through api (invariant 9, T4).
    with pytest.raises(ProgrammingError, match=DENIED):
        run(
            gateway,
            seed.user_a,
            "UPDATE app.settings SET work_start = '00:00' WHERE user_id = :u",
            u=seed.user_a,
        )
