"""SqlApiStore against the real database, as api_service (T3, T10, T13, E7)."""

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from api.store import ApproveResult, SqlApiStore

pytestmark = pytest.mark.db

HASH = "sha256:" + "c" * 64


@pytest.fixture
def two_users(owner: Engine) -> Iterator[tuple[UUID, UUID]]:
    a, b = uuid4(), uuid4()
    with owner.begin() as conn:
        for uid in (a, b):
            conn.execute(
                text("INSERT INTO app.users (user_id, email) VALUES (:id, :e)"),
                {"id": uid, "e": f"user-{uid}@example.com"},
            )
    yield a, b
    with owner.begin() as conn:
        for uid in (a, b):
            conn.execute(text("DELETE FROM app.users WHERE user_id = :id"), {"id": uid})
            conn.execute(text("DELETE FROM app.audit_log WHERE user_id = :id"), {"id": uid})


def add_action(owner: Engine, user: UUID, expires_in_minutes: int = 60) -> UUID:
    action = uuid4()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.pending_actions"
                " (action_id, user_id, kind, payload, content_hash, expires_at)"
                " VALUES (:a, :u, 'reply_with_slots', CAST(:p AS jsonb), :h,"
                " now() + make_interval(mins => :m))"
            ),
            {
                "a": action,
                "u": user,
                "p": json.dumps({"to": ["dana@example.org"]}),
                "h": HASH,
                "m": expires_in_minutes,
            },
        )
    return action


def test_approve_records_a_single_use_approval(
    api: Engine, owner: Engine, two_users: tuple[UUID, UUID]
) -> None:
    a, _ = two_users
    action = add_action(owner, a)
    store = SqlApiStore(api)
    assert store.approve(a, action, HASH) is ApproveResult.APPROVED
    assert store.approve(a, action, HASH) is ApproveResult.NOT_PENDING
    with owner.begin() as conn:
        approvals = conn.execute(
            text("SELECT content_hash, channel FROM app.approvals WHERE action_id = :a"),
            {"a": action},
        ).all()
        status = conn.execute(
            text("SELECT status FROM app.pending_actions WHERE action_id = :a"), {"a": action}
        ).scalar_one()
    assert [tuple(r) for r in approvals] == [(HASH, "web")]
    assert status == "approved"


def test_t3_a_different_hash_records_nothing(
    api: Engine, owner: Engine, two_users: tuple[UUID, UUID]
) -> None:
    a, _ = two_users
    action = add_action(owner, a)
    assert SqlApiStore(api).approve(a, action, "sha256:" + "d" * 64) is ApproveResult.HASH_MISMATCH
    assert SqlApiStore(api).action(a, action).status == "pending"  # type: ignore[union-attr]


def test_e7_expired(api: Engine, owner: Engine, two_users: tuple[UUID, UUID]) -> None:
    a, _ = two_users
    action = add_action(owner, a, expires_in_minutes=-1)
    assert SqlApiStore(api).approve(a, action, HASH) is ApproveResult.EXPIRED


def test_t13_another_users_action_is_invisible_and_unapprovable(
    api: Engine, owner: Engine, two_users: tuple[UUID, UUID]
) -> None:
    a, b = two_users
    action = add_action(owner, a)
    store = SqlApiStore(api)
    assert store.action(b, action) is None
    assert store.approve(b, action, HASH) is ApproveResult.NOT_FOUND
    assert not store.reject(b, action)
    assert store.action(a, action).status == "pending"  # type: ignore[union-attr]


def test_t10_the_database_allows_one_approval_per_action(
    api: Engine, owner: Engine, two_users: tuple[UUID, UUID]
) -> None:
    a, _ = two_users
    action = add_action(owner, a)
    SqlApiStore(api).approve(a, action, HASH)
    with pytest.raises(Exception, match="approvals_one_per_action"), api.begin() as conn:
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(a)})
        conn.execute(
            text(
                "INSERT INTO app.approvals (user_id, action_id, content_hash, channel)"
                " VALUES (:u, :a, :h, 'web')"
            ),
            {"u": a, "a": action, "h": HASH},
        )


def test_t3_the_api_role_cannot_change_an_actions_content(
    api: Engine, owner: Engine, two_users: tuple[UUID, UUID]
) -> None:
    a, _ = two_users
    action = add_action(owner, a)
    with pytest.raises(Exception, match="permission denied"), api.begin() as conn:
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(a)})
        conn.execute(
            text("UPDATE app.pending_actions SET payload = '{}' WHERE action_id = :a"),
            {"a": action},
        )


def test_find_user_and_profile(api: Engine, two_users: tuple[UUID, UUID]) -> None:
    a, _ = two_users
    store = SqlApiStore(api)
    assert store.find_user(f"USER-{a}@example.com") == a
    user = store.user(a)
    assert user is not None and user.status == "active"
