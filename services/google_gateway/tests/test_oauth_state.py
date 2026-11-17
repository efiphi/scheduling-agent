"""RedisStateStore against a minimal fake of the two Redis commands it uses."""

from uuid import uuid4

from google_gateway.oauth_state import (
    STATE_TTL_SECONDS,
    PendingConnect,
    RedisStateStore,
    new_code_verifier,
    new_state,
)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.set_calls: list[dict[str, object]] = []
        self.getdel_calls: list[str] = []

    def set(self, key: str, value: str, ex: int, nx: bool) -> bool:
        self.set_calls.append({"key": key, "ex": ex, "nx": nx})
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def getdel(self, key: str) -> str | None:
        self.getdel_calls.append(key)
        return self.data.pop(key, None)


def store() -> tuple[RedisStateStore, FakeRedis]:
    redis = FakeRedis()
    return RedisStateStore(redis), redis  # type: ignore[arg-type]


def test_round_trip_then_gone() -> None:
    states, _ = store()
    state = new_state()
    pending = PendingConnect(user_id=uuid4(), code_verifier=new_code_verifier())
    states.put(state, pending)
    assert states.take(state) == pending
    assert states.take(state) is None


def test_state_expires_after_ten_minutes_and_is_never_overwritten() -> None:
    states, redis = store()
    states.put(new_state(), PendingConnect(user_id=uuid4(), code_verifier=new_code_verifier()))
    assert redis.set_calls[0]["ex"] == STATE_TTL_SECONDS == 600
    assert redis.set_calls[0]["nx"] is True


def test_malformed_state_is_not_looked_up() -> None:
    states, redis = store()
    for bad in ("", "short", "x" * 43 + "*", "a" * 44, "oauth-state:*"):
        assert states.take(bad) is None
    assert redis.getdel_calls == []


def test_values_are_random_and_long_enough() -> None:
    assert len({new_state() for _ in range(100)}) == 100
    assert len(new_state()) == 43
    assert 43 <= len(new_code_verifier()) <= 128
