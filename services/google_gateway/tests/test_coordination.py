"""RedisCoordination and RedisStateStore against a real Redis (E8, T24)."""

from typing import cast
from uuid import uuid4

import pytest
from mail_fakes import NOW, FakeMailStore
from redis import Redis

from google_gateway.coordination import (
    MAX_PER_SENDER_PER_HOUR,
    MAX_PER_USER_PER_HOUR,
    RATE_WINDOW_SECONDS,
    RedisCoordination,
)
from google_gateway.oauth_state import (
    PendingConnect,
    RedisStateStore,
    new_code_verifier,
    new_state,
)
from shared.messages import EmailTask, UntrustedEmail, UntrustedText

pytestmark = pytest.mark.redis

STREAM = "test:email-tasks"


def test_only_one_poller_gets_a_mailbox(redis_client: Redis) -> None:
    coord, user = RedisCoordination(redis_client), uuid4()
    with coord.lock_user(user) as first, coord.lock_user(user) as second:
        assert first and not second
    with coord.lock_user(user) as again:
        assert again  # released after the first poller finished


def test_e8_handled_markers_expire_after_a_week(redis_client: Redis) -> None:
    coord, user = RedisCoordination(redis_client), uuid4()
    assert not coord.already_handled(user, "m1")
    coord.mark_handled(user, "m1")
    assert coord.already_handled(user, "m1")
    assert not coord.already_handled(uuid4(), "m1")  # per user
    assert 0 < redis_client.ttl(f"handled:gmail:{user}:m1") <= 7 * 24 * 3600


def test_t24_one_sender_is_capped_per_hour(redis_client: Redis) -> None:
    coord, user = RedisCoordination(redis_client), uuid4()
    results = [coord.take_rate_slot(user, "flood@example.org") for _ in range(8)]
    assert results == [True] * MAX_PER_SENDER_PER_HOUR + [False] * (8 - MAX_PER_SENDER_PER_HOUR)
    # Another sender still gets through.
    assert coord.take_rate_slot(user, "dana@example.org")


def test_t24_a_user_is_capped_per_hour_across_senders(redis_client: Redis) -> None:
    coord, user = RedisCoordination(redis_client), uuid4()
    results = [coord.take_rate_slot(user, f"s{i}@example.org") for i in range(25)]
    assert results.count(True) == MAX_PER_USER_PER_HOUR


def test_rate_window_is_not_extended_by_later_emails(redis_client: Redis) -> None:
    coord, user = RedisCoordination(redis_client), uuid4()
    coord.take_rate_slot(user, "a@example.org")
    redis_client.expire(f"rate:email:user:{user}", 10)
    coord.take_rate_slot(user, "a@example.org")
    assert redis_client.ttl(f"rate:email:user:{user}") <= 10 < RATE_WINDOW_SECONDS


def test_sender_addresses_stay_out_of_redis_keys(redis_client: Redis) -> None:
    RedisCoordination(redis_client).take_rate_slot(uuid4(), "dana@example.org")
    assert not any(b"dana" in key for key in redis_client.keys("*"))


def test_tasks_go_to_the_stream_as_validated_json(redis_client: Redis) -> None:
    user = uuid4()
    task = EmailTask(
        task_id=uuid4(),
        user_id=user,
        thread_id=uuid4(),
        email=UntrustedEmail(
            gmail_message_id="m1",
            sender="dana@example.org",
            subject=UntrustedText("Call?"),
            body_text=UntrustedText("Tuesday?"),
            received_at=NOW,
        ),
        context=FakeMailStore().agent_context(user, NOW),
    )
    RedisCoordination(redis_client, stream=STREAM).enqueue(task)
    entries = cast(list[tuple[bytes, dict[bytes, bytes]]], redis_client.xrange(STREAM))
    [(_, fields)] = entries
    assert EmailTask.model_validate_json(fields[b"task"]) == task


def test_oauth_state_is_single_use_with_a_ten_minute_expiry(redis_client: Redis) -> None:
    states, state = RedisStateStore(redis_client), new_state()
    pending = PendingConnect(user_id=uuid4(), code_verifier=new_code_verifier())
    states.put(state, pending)
    assert 0 < redis_client.ttl(f"oauth-state:{state}") <= 600
    assert states.take(state) == pending
    assert states.take(state) is None


def test_t13_task_owner_is_recorded_when_a_task_is_queued(redis_client: Redis) -> None:
    user = uuid4()
    task = EmailTask(
        task_id=uuid4(),
        user_id=user,
        thread_id=uuid4(),
        email=UntrustedEmail(
            gmail_message_id="m1",
            sender="dana@example.org",
            subject=UntrustedText("Call?"),
            body_text=UntrustedText("Tuesday?"),
            received_at=NOW,
        ),
        context=FakeMailStore().agent_context(user, NOW),
    )
    coord = RedisCoordination(redis_client, stream=STREAM)
    coord.enqueue(task)
    assert coord.task_owner(task.task_id) == user
    assert coord.task_owner(uuid4()) is None
    assert 0 < redis_client.ttl(f"task-owner:{task.task_id}") <= 24 * 3600
