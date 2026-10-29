"""What the poller keeps in Redis (ADR-004): locks, "already handled", rate limits, the queue.

- A lock per user, so two pollers (a slow run and the next minute's, or two replicas)
  never process one mailbox at the same time.
- "Handled" markers for 7 days, so an email seen twice (a crash before the history id was
  saved, or the resync after an expired history id) reaches the agent once (E8).
- Counters that cap how many emails per hour reach the agent, per user and per sender,
  so a flood of meeting-like emails cannot burn the LLM budget (T24).
- The task queue to the agent: a Redis Stream, read by the agent's consumer group.
- Who each task belongs to, for a day. The agent can only ask about the calendar of the
  user a task was issued for: a manipulated agent cannot ask for someone else's (T13).
"""

import hashlib
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from typing import Protocol
from uuid import UUID

from redis import Redis
from redis.exceptions import LockError

from shared.messages import EmailTask
from shared.streams import EMAIL_TASKS, STREAM_MAX_LENGTH

LOCK_SECONDS = 120
HANDLED_SECONDS = 7 * 24 * 3600
TASK_OWNER_SECONDS = 24 * 3600
RATE_WINDOW_SECONDS = 3600
MAX_PER_USER_PER_HOUR = 20
MAX_PER_SENDER_PER_HOUR = 5


class PollCoordination(Protocol):
    def lock_user(self, user_id: UUID) -> AbstractContextManager[bool]:
        """Yields True if this poller got the user's mailbox, False if another one has it."""
        ...

    def already_handled(self, user_id: UUID, message_id: str) -> bool: ...

    def mark_handled(self, user_id: UUID, message_id: str) -> None: ...

    def take_rate_slot(self, user_id: UUID, sender: str) -> bool:
        """Count one more email to the agent; False if the user or sender is over the cap."""
        ...

    def enqueue(self, task: EmailTask) -> None: ...

    def task_owner(self, task_id: UUID) -> UUID | None: ...


class RedisCoordination:
    def __init__(self, redis: Redis, stream: str = EMAIL_TASKS) -> None:
        self._redis = redis
        self._stream = stream

    @contextmanager
    def lock_user(self, user_id: UUID) -> Iterator[bool]:
        lock = self._redis.lock(f"lock:poll:{user_id}", timeout=LOCK_SECONDS, blocking=False)
        acquired = bool(lock.acquire())
        try:
            yield acquired
        finally:
            if acquired:
                # If it expired while we worked, there is nothing to release.
                with suppress(LockError):
                    lock.release()

    def already_handled(self, user_id: UUID, message_id: str) -> bool:
        return bool(self._redis.exists(_handled_key(user_id, message_id)))

    def mark_handled(self, user_id: UUID, message_id: str) -> None:
        self._redis.set(_handled_key(user_id, message_id), 1, ex=HANDLED_SECONDS)

    def take_rate_slot(self, user_id: UUID, sender: str) -> bool:
        # The sender is hashed: email addresses stay out of Redis key names.
        sender_hash = hashlib.sha256(sender.encode()).hexdigest()[:32]
        user_key = f"rate:email:user:{user_id}"
        sender_key = f"rate:email:sender:{user_id}:{sender_hash}"
        pipe = self._redis.pipeline()
        for key in (user_key, sender_key):
            pipe.incr(key)
            # nx: the window starts with the first email and is not extended by later ones.
            pipe.expire(key, RATE_WINDOW_SECONDS, nx=True)
        user_count, _, sender_count, _ = pipe.execute()
        return int(user_count) <= MAX_PER_USER_PER_HOUR and (
            int(sender_count) <= MAX_PER_SENDER_PER_HOUR
        )

    def enqueue(self, task: EmailTask) -> None:
        # Recorded before the task is visible, so the agent can never ask about it first.
        self._redis.set(_owner_key(task.task_id), str(task.user_id), ex=TASK_OWNER_SECONDS)
        self._redis.xadd(
            self._stream,
            {"task": task.model_dump_json()},
            maxlen=STREAM_MAX_LENGTH,
            approximate=True,
        )

    def task_owner(self, task_id: UUID) -> UUID | None:
        owner = self._redis.get(_owner_key(task_id))
        return (
            None
            if owner is None
            else UUID(owner.decode() if isinstance(owner, bytes) else str(owner))
        )


def _owner_key(task_id: UUID) -> str:
    return f"task-owner:{task_id}"


def _handled_key(user_id: UUID, message_id: str) -> str:
    return f"handled:gmail:{user_id}:{message_id}"
