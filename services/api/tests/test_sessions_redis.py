"""RedisSessionStore against a real Redis (T10, T11)."""

from uuid import uuid4

import pytest
from redis import Redis

from api.sessions import IDLE_SECONDS, LoginState, RedisSessionStore

pytestmark = pytest.mark.redis


def test_session_round_trip_and_raw_id_not_stored(redis_client: Redis) -> None:
    store, user = RedisSessionStore(redis_client), uuid4()
    session = store.create(user)
    found = store.get(session.session_id)
    assert found is not None and found.data.user_id == user
    # Only a hash of the id is a key in Redis: a dump does not give usable session ids.
    assert not any(session.session_id.encode() in key for key in redis_client.keys("*"))
    assert 0 < max(redis_client.ttl(k) for k in redis_client.keys("session:*")) <= IDLE_SECONDS


def test_unknown_or_malformed_session_ids(redis_client: Redis) -> None:
    store = RedisSessionStore(redis_client)
    for bad in ("", "x" * 500, "not-a-session"):
        assert store.get(bad) is None


def test_t11_logout_everywhere(redis_client: Redis) -> None:
    store, user = RedisSessionStore(redis_client), uuid4()
    one, two = store.create(user), store.create(user)
    other = store.create(uuid4())
    assert store.delete_all(user) == 2
    assert store.get(one.session_id) is None and store.get(two.session_id) is None
    assert store.get(other.session_id) is not None


def test_login_state_is_single_use(redis_client: Redis) -> None:
    store = RedisSessionStore(redis_client)
    store.put_login_state("state-1", LoginState(code_verifier="v"))
    assert store.take_login_state("state-1") == LoginState(code_verifier="v")
    assert store.take_login_state("state-1") is None
