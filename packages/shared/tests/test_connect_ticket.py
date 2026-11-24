"""The api-to-gateway connect ticket (T16): once, briefly, stored by hash only."""

from uuid import uuid4

from shared import connect_ticket


class MemoryRedis:
    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, name: str, value: str, ex: int, nx: bool) -> bool:
        if nx and name in self.items:
            return False
        self.items[name], self.ttls[name] = value, ex
        return True

    def getdel(self, name: str) -> str | None:
        return self.items.pop(name, None)


def test_t16_a_ticket_works_once() -> None:
    redis, user = MemoryRedis(), uuid4()
    ticket = connect_ticket.issue(redis, user, "onboarding")
    found = connect_ticket.redeem(redis, ticket)
    assert found is not None
    assert (found.user_id, found.return_to) == (user, "onboarding")
    assert connect_ticket.redeem(redis, ticket) is None


def test_t16_redis_holds_only_the_tickets_hash_for_five_minutes() -> None:
    redis = MemoryRedis()
    ticket = connect_ticket.issue(redis, uuid4(), "settings/security")
    (key,) = redis.items
    assert ticket not in key
    assert redis.ttls[key] == 300


def test_t16_malformed_or_unknown_tickets_are_refused() -> None:
    redis = MemoryRedis()
    connect_ticket.issue(redis, uuid4(), "onboarding")
    for ticket in ("", "short", "x" * 43, "../../etc" + "a" * 34):
        assert connect_ticket.redeem(redis, ticket) is None
