"""The agent process: read email tasks from Redis, run the graph, publish plans.

    python -m agent.worker

- Consumer group on the task stream (ADR-004): each task goes to one agent replica, and a
  task stays pending until acknowledged. It is acknowledged only after its plan is
  published, so a crash mid-task means a retry, not a lost email. Plans carry the task id,
  so the gateway can drop a duplicate (E8).
- A task older than a few minutes that another replica left pending is claimed again.
- A message that is not a valid EmailTask is moved aside (dead letter) and acknowledged,
  so one bad message cannot block the queue.
- Daily spend cap (T24, ADR-015): every model call adds its cost to a counter for the day.
  Over the cap, the agent stops taking tasks; they wait in the queue until the next day.

Environment: ANTHROPIC_API_KEY (the agent's only secret), REDIS_HOST/PORT/PASSWORD,
AGENT_DAILY_BUDGET_USD (default 1.00). No database, no Google credentials (ADR-011).
"""

import logging
import os
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from agent.extraction import MODEL, AnthropicFormFiller, Usage
from agent.free_busy import RedisFreeBusyClient
from agent.graph import AgentState, build_graph, run
from shared.messages import EmailTask
from shared.streams import (
    AGENT_PLANS,
    EMAIL_TASKS,
    REDIS_SOCKET_TIMEOUT_SECONDS,
    STREAM_MAX_LENGTH,
)

logger = logging.getLogger(__name__)

GROUP = "agent"
DEAD_LETTER = "agent:dead-letter"
BLOCK_MS = 5_000
RECLAIM_IDLE_MS = 5 * 60 * 1000
# USD per million tokens (input, output). Haiku 5.5 list price (ADR-015).
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (3.0, 15.0)}
DEFAULT_DAILY_BUDGET_USD = 1.0


def cost_usd(usage: Usage, model: str = MODEL) -> float:
    price_in, price_out = PRICES[model]
    return (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000


class SpendCap:
    """A per-day cost counter in Redis, shared by all agent replicas (T24)."""

    def __init__(self, redis: Redis, budget_usd: float, clock: Callable[[], datetime]) -> None:
        self._redis = redis
        self._budget = budget_usd
        self._clock = clock

    def _key(self) -> str:
        return f"cost:agent:{self._clock().astimezone(UTC):%Y-%m-%d}"

    def exhausted(self) -> bool:
        spent = self._redis.get(self._key())
        return spent is not None and float(spent) >= self._budget

    def add(self, usd: float) -> None:
        key = self._key()
        self._redis.incrbyfloat(key, usd)
        self._redis.expire(key, 2 * 24 * 3600)


class Worker:
    def __init__(
        self,
        redis: Redis,
        graph: CompiledStateGraph[AgentState, None, AgentState, AgentState],
        cap: SpendCap,
        consumer: str,
    ) -> None:
        self._redis = redis
        self._graph = graph
        self._cap = cap
        self._consumer = consumer
        self._paused_logged = False

    def ensure_group(self) -> None:
        try:
            self._redis.xgroup_create(EMAIL_TASKS, GROUP, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    def step(self) -> int:
        """Handle at most one task. Returns how many were handled (0 or 1)."""
        if self._cap.exhausted():
            if not self._paused_logged:
                logger.warning("daily spend cap reached: agent paused until tomorrow (T24)")
                self._paused_logged = True
            time.sleep(BLOCK_MS / 1000)
            return 0
        self._paused_logged = False
        entry = self._reclaim() or self._read()
        if entry is None:
            return 0
        message_id, fields = entry
        self._handle(message_id, fields)
        return 1

    def _reclaim(self) -> tuple[str, dict[bytes, bytes]] | None:
        _, claimed, *_ = self._redis.xautoclaim(
            EMAIL_TASKS, GROUP, self._consumer, min_idle_time=RECLAIM_IDLE_MS, count=1
        )
        return _first(claimed)

    def _read(self) -> tuple[str, dict[bytes, bytes]] | None:
        response: Any = self._redis.xreadgroup(
            GROUP, self._consumer, {EMAIL_TASKS: ">"}, count=1, block=BLOCK_MS
        )
        if not response:
            return None
        return _first(response[0][1])

    def _handle(self, message_id: str, fields: dict[bytes, bytes]) -> None:
        try:
            task = EmailTask.model_validate_json(fields.get(b"task", b""))
        except ValidationError:
            # Not ours to guess at. Keep it for inspection, then move on.
            self._redis.xadd(DEAD_LETTER, {"message_id": message_id}, maxlen=1000)
            self._redis.xack(EMAIL_TASKS, GROUP, message_id)
            logger.error("invalid task moved to dead letter: message_id=%s", message_id)
            return
        plan, usage = run(self._graph, task)
        self._cap.add(cost_usd(usage))
        self._redis.xadd(
            AGENT_PLANS,
            {"plan": plan.model_dump_json()},
            maxlen=STREAM_MAX_LENGTH,
            approximate=True,
        )
        self._redis.xack(EMAIL_TASKS, GROUP, message_id)
        # Ids and the decision kind only: never email content (T22).
        logger.info(
            "plan published: task_id=%s decision=%s tokens=%d+%d",
            task.task_id,
            plan.decision.kind,
            usage.input_tokens,
            usage.output_tokens,
        )


def _first(entries: Any) -> tuple[str, dict[bytes, bytes]] | None:
    if not entries:
        return None
    message_id, fields = entries[0]
    if fields is None:  # deleted from the stream while pending
        return None
    raw_id = message_id.decode() if isinstance(message_id, bytes) else str(message_id)
    return raw_id, fields


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # The HTTP clients log request details at INFO; keep them quiet (T22).
    for noisy in ("httpx", "httpx2", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set (see deploy/compose/.env.example)")

    redis = Redis(
        host=os.environ.get("REDIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=os.environ["REDIS_PASSWORD"],
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
    )
    clock = lambda: datetime.now(UTC)  # noqa: E731
    graph = build_graph(AnthropicFormFiller(), RedisFreeBusyClient(redis), clock)
    budget = float(os.environ.get("AGENT_DAILY_BUDGET_USD", DEFAULT_DAILY_BUDGET_USD))
    worker = Worker(redis, graph, SpendCap(redis, budget, clock), consumer=socket.gethostname())
    worker.ensure_group()
    logger.info("agent started: model=%s daily_budget_usd=%.2f", MODEL, budget)
    while True:
        try:
            worker.step()
        except (RedisTimeoutError, RedisConnectionError) as exc:
            # A Redis hiccup is not a reason to die; the task stays pending and is retried.
            logger.warning("redis unavailable, retrying: error=%s", type(exc).__name__)
            time.sleep(1)


if __name__ == "__main__":
    main()
