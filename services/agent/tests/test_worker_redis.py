"""The agent worker and the free/busy client against a real Redis (ADR-004, E8, T24)."""

import threading
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from agent_fakes import NOW, FakeFiller, task
from redis import Redis
from test_graph import FakeGateway

from agent.extraction import Usage
from agent.free_busy import RedisFreeBusyClient
from agent.graph import build_graph
from agent.worker import DEAD_LETTER, GROUP, SpendCap, Worker, cost_usd
from shared.messages import AgentPlan, FreeBusyReply, FreeBusyRequest, Interval
from shared.streams import AGENT_PLANS, EMAIL_TASKS, FREE_BUSY_REQUESTS, free_busy_reply_key

pytestmark = pytest.mark.redis

Entries = list[tuple[bytes, dict[bytes, bytes]]]


def worker(redis: Redis, budget: float = 1.0, filler: FakeFiller | None = None) -> Worker:
    graph = build_graph(filler or FakeFiller(), FakeGateway(), lambda: NOW)
    w = Worker(redis, graph, SpendCap(redis, budget, lambda: NOW), consumer="test")
    w.ensure_group()
    return w


def test_a_task_becomes_a_plan_and_is_acknowledged_after(redis_client: Redis) -> None:
    w = worker(redis_client)
    t = task()
    redis_client.xadd(EMAIL_TASKS, {"task": t.model_dump_json()})
    assert w.step() == 1
    [(_, fields)] = cast(Entries, redis_client.xrange(AGENT_PLANS))
    plan = AgentPlan.model_validate_json(fields[b"plan"])
    assert plan.task_id == t.task_id and plan.decision.kind == "propose_slots"
    assert redis_client.xpending(EMAIL_TASKS, GROUP)["pending"] == 0


def test_an_invalid_task_goes_to_the_dead_letter_and_does_not_block(redis_client: Redis) -> None:
    w = worker(redis_client)
    redis_client.xadd(EMAIL_TASKS, {"task": '{"not": "a task"}'})
    redis_client.xadd(EMAIL_TASKS, {"task": task().model_dump_json()})
    assert w.step() == 1 and w.step() == 1
    assert redis_client.xlen(DEAD_LETTER) == 1
    assert redis_client.xlen(AGENT_PLANS) == 1
    assert redis_client.xpending(EMAIL_TASKS, GROUP)["pending"] == 0


def test_t24_over_the_daily_cap_tasks_wait_in_the_queue(redis_client: Redis) -> None:
    filler = FakeFiller()
    w = worker(redis_client, budget=0.000001, filler=filler)
    redis_client.xadd(EMAIL_TASKS, {"task": task().model_dump_json()})
    redis_client.xadd(EMAIL_TASKS, {"task": task().model_dump_json()})
    assert w.step() == 1  # the first call crosses the tiny cap
    assert w.step() == 0  # paused: the second task is not read
    assert filler.calls == 1
    assert redis_client.xlen(AGENT_PLANS) == 1


def test_spend_is_counted_per_day(redis_client: Redis) -> None:
    cap = SpendCap(redis_client, 1.0, lambda: NOW)
    cap.add(cost_usd(Usage(1_000_000, 0)))  # $0.10 of input on Haiku
    assert float(redis_client.get(f"cost:agent:{NOW:%Y-%m-%d}") or 0) == pytest.approx(0.10)
    later = SpendCap(redis_client, 1.0, lambda: datetime(2026, 11, 3, tzinfo=UTC))
    assert not later.exhausted()


def test_free_busy_request_and_reply_over_redis(redis_client: Redis) -> None:
    busy = (Interval(start=NOW, end=NOW.replace(hour=8)),)

    def gateway() -> None:
        # Plays google-gateway: read one request, answer on the reply key.
        response = redis_client.xread({FREE_BUSY_REQUESTS: "0"}, count=1, block=5000)
        request = FreeBusyRequest.model_validate_json(response[0][1][0][1][b"request"])  # type: ignore[index]
        reply = FreeBusyReply(request_id=request.request_id, status="ok", busy=busy)
        redis_client.lpush(free_busy_reply_key(request.request_id), reply.model_dump_json())

    thread = threading.Thread(target=gateway)
    thread.start()
    request = FreeBusyRequest(
        request_id=uuid4(),
        task_id=uuid4(),
        user_id=uuid4(),
        window=Interval(start=NOW, end=NOW.replace(hour=20)),
    )
    reply = RedisFreeBusyClient(redis_client, timeout_seconds=5).ask(request)
    thread.join()
    assert reply is not None and reply.busy == busy


def test_e13_no_reply_in_time_is_none_not_free(redis_client: Redis) -> None:
    request = FreeBusyRequest(
        request_id=uuid4(),
        task_id=uuid4(),
        user_id=uuid4(),
        window=Interval(start=NOW, end=NOW.replace(hour=20)),
    )
    assert RedisFreeBusyClient(redis_client, timeout_seconds=1).ask(request) is None


def test_a_reply_for_another_request_is_ignored(redis_client: Redis) -> None:
    request = FreeBusyRequest(
        request_id=uuid4(),
        task_id=uuid4(),
        user_id=uuid4(),
        window=Interval(start=NOW, end=NOW.replace(hour=20)),
    )
    wrong = FreeBusyReply(request_id=uuid4(), status="ok")
    redis_client.lpush(free_busy_reply_key(request.request_id), wrong.model_dump_json())
    assert RedisFreeBusyClient(redis_client, timeout_seconds=1).ask(request) is None
