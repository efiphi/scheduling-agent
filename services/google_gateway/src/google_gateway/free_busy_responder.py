"""Answering the agent's free/busy requests (ADR-011, invariant 5, step 1.7).

    python -m google_gateway.free_busy_responder

For each FreeBusyRequest on the request stream:
1. The task must be one this gateway issued, for this same user (task owner in Redis).
   A manipulated agent cannot ask about another user's calendar (T13), or invent tasks.
2. The user must still be connected. Otherwise, or on any failure, the answer is
   "unavailable", which the agent turns into a question, never into "free" (E1, E13).
3. Busy intervals only go back: no titles, no attendees (invariant 5, calendar.py).
The reply is pushed to a key named after the request and expires if nobody reads it.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from google.auth.exceptions import RefreshError
from pydantic import ValidationError
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from google_gateway.calendar import CalendarReader, busy_intervals
from google_gateway.coordination import PollCoordination
from google_gateway.mail_store import MailStore
from google_gateway.token_crypto import EncryptedToken
from shared import log, metrics, tracing
from shared.messages import FreeBusyReply, FreeBusyRequest
from shared.streams import FREE_BUSY_REQUESTS, REPLY_TTL_SECONDS, free_busy_reply_key

logger = logging.getLogger(__name__)
_tracer = tracing.tracer(__name__)

GROUP = "gateway"
BLOCK_MS = 5_000

OpenCalendar = Callable[[UUID, EncryptedToken, str], CalendarReader]


@dataclass(frozen=True)
class FreeBusyResponder:
    redis: Redis
    store: MailStore
    coordination: PollCoordination
    open_calendar: OpenCalendar
    consumer: str = "gateway"

    def ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(FREE_BUSY_REQUESTS, GROUP, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    def step(self) -> int:
        response: Any = self.redis.xreadgroup(
            GROUP, self.consumer, {FREE_BUSY_REQUESTS: ">"}, count=1, block=BLOCK_MS
        )
        if not response:
            return 0
        message_id, fields = response[0][1][0]
        try:
            request = FreeBusyRequest.model_validate_json(fields.get(b"request", b""))
        except ValidationError:
            logger.error("invalid free/busy request dropped")
        else:
            with _tracer.start_as_current_span(
                "freebusy.answer", context=tracing.extract(fields)
            ) as span:
                reply = self.answer(request)
                span.set_attribute("freebusy.status", reply.status)
                span.set_attribute("freebusy.busy_count", len(reply.busy))
            key = free_busy_reply_key(request.request_id)
            pipe = self.redis.pipeline()
            pipe.lpush(key, reply.model_dump_json())
            pipe.expire(key, REPLY_TTL_SECONDS)
            pipe.execute()
            logger.info(
                "free/busy answered: request_id=%s status=%s busy=%d",
                request.request_id,
                reply.status,
                len(reply.busy),
            )
        self.redis.xack(FREE_BUSY_REQUESTS, GROUP, message_id)
        return 1

    def answer(self, request: FreeBusyRequest) -> FreeBusyReply:
        unavailable = FreeBusyReply(request_id=request.request_id, status="unavailable")
        if self.coordination.task_owner(request.task_id) != request.user_id:
            # Not a task we issued for this user: possibly a manipulated agent (T13).
            self.store.security_event(request.user_id, "free_busy_task_mismatch", {})
            return unavailable
        mailbox = self.store.mailbox(request.user_id)
        if mailbox is None:
            return unavailable
        time_zone = self.store.agent_context(request.user_id, datetime.now(UTC)).time_zone
        try:
            calendar = self.open_calendar(request.user_id, mailbox.token, time_zone)
            events = calendar.events(request.window)
        except RefreshError:
            self.store.mark_expired(request.user_id)  # E13: stop until the user reconnects
            return unavailable
        except Exception as exc:
            logger.error("calendar read failed: error=%s", type(exc).__name__)
            return unavailable
        return FreeBusyReply(
            request_id=request.request_id,
            status="ok",
            busy=busy_intervals(events, request.window),
        )


def main() -> None:
    import socket

    from google_gateway.config import GatewayConfig
    from google_gateway.wiring import free_busy_responder

    # JSON lines with the trace id; quiet HTTP clients and redaction (shared.log, T22).
    log.configure("calendar-responder")
    tracing.configure("calendar-responder")
    metrics.configure("calendar-responder")
    responder = free_busy_responder(GatewayConfig.from_env(), consumer=socket.gethostname())
    responder.ensure_group()
    metrics.observe_stream_backlog(responder.redis, FREE_BUSY_REQUESTS, GROUP)
    while True:
        try:
            responder.step()
        except (RedisTimeoutError, RedisConnectionError) as exc:
            # A Redis hiccup is not a reason to die; unacknowledged work is retried.
            logger.warning("redis unavailable, retrying: error=%s", type(exc).__name__)
            time.sleep(1)


if __name__ == "__main__":
    main()
