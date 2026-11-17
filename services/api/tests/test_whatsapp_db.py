"""WhatsApp data in the real database and Redis (T13, ADR-014)."""

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from redis import Redis
from sqlalchemy import Engine, text

from api.store import SqlApiStore
from api.whatsapp import InboxState


@pytest.fixture
def user(owner: Engine) -> Iterator[UUID]:
    uid = uuid4()
    with owner.begin() as conn:
        conn.execute(
            text("INSERT INTO app.users (user_id, email) VALUES (:id, :e)"),
            {"id": uid, "e": f"user-{uid}@example.com"},
        )
    yield uid
    with owner.begin() as conn:
        conn.execute(text("DELETE FROM app.users WHERE user_id = :id"), {"id": uid})
        conn.execute(text("DELETE FROM app.audit_log WHERE user_id = :id"), {"id": uid})
        conn.execute(text("DELETE FROM app.security_events WHERE user_id = :id"), {"id": uid})


@pytest.mark.db
def test_senders_are_found_by_number_with_their_role(api: Engine, user: UUID) -> None:
    store = SqlApiStore(api)
    number, backup = f"9725{uuid4().int % 10**8:08d}", f"9726{uuid4().int % 10**8:08d}"
    assert store.bind_whatsapp_number(user, number)
    store.set_backup_numbers(user, [backup])
    assert store.whatsapp_senders(number) == [(user, "owner")]
    assert store.whatsapp_senders(backup) == [(user, "backup")]
    assert store.whatsapp_senders("972500000000") == []
    assert store.backup_numbers(user) == [backup]


@pytest.mark.db
def test_a_verified_number_belongs_to_one_user(api: Engine, owner: Engine, user: UUID) -> None:
    other = uuid4()
    with owner.begin() as conn:
        conn.execute(
            text("INSERT INTO app.users (user_id, email) VALUES (:id, :e)"),
            {"id": other, "e": f"user-{other}@example.com"},
        )
    try:
        number = f"9727{uuid4().int % 10**8:08d}"
        store = SqlApiStore(api)
        assert store.bind_whatsapp_number(user, number)
        assert not store.bind_whatsapp_number(other, number)
    finally:
        with owner.begin() as conn:
            conn.execute(text("DELETE FROM app.users WHERE user_id = :id"), {"id": other})
            conn.execute(text("DELETE FROM app.audit_log WHERE user_id = :id"), {"id": other})


@pytest.mark.db
def test_t13_the_gateway_cannot_look_up_whatsapp_senders(gateway: Engine) -> None:
    with pytest.raises(Exception, match="permission denied"), gateway.begin() as conn:
        conn.execute(text("SELECT * FROM app.whatsapp_senders('972500000000')"))


@pytest.mark.db
def test_pause_cancels_pending_actions(api: Engine, owner: Engine, user: UUID) -> None:
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.pending_actions (user_id, kind, payload, content_hash, expires_at)"
                " VALUES (:u, 'reply_with_slots', '{}', 'sha256:x', now() + interval '1 hour')"
            ),
            {"u": user},
        )
    store = SqlApiStore(api)
    assert store.pause(user, "whatsapp_stop") == 1
    assert store.user(user).status == "paused"  # type: ignore[union-attr]
    assert store.actions(user, "pending") == []
    store.resume(user)
    assert store.user(user).status == "active"  # type: ignore[union-attr]


@pytest.mark.redis
def test_verification_codes_are_single_use_and_stored_hashed(redis_client: Redis) -> None:
    state, user = InboxState(redis_client), uuid4()
    code = state.start_verification(user)
    assert not any(code.encode() in k for k in redis_client.keys("*"))
    assert state.take_verification(f"אימות {code.lower()}") == user
    assert state.take_verification(code) is None


@pytest.mark.redis
def test_rate_limits_and_the_window(redis_client: Redis) -> None:
    state, user = InboxState(redis_client), uuid4()
    assert not any(state.over_limit("stop", "972500000002", (3, 60)) for _ in range(3))
    assert state.limited("stop", "972500000002", (3, 60))
    assert state.over_limit("stop", "972500000002", (3, 60))
    assert not state.window_open(user)
    state.open_window(user)
    assert state.window_open(user)
