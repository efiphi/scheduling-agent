"""Asking google-gateway when the user is busy, over Redis (ADR-011, invariant 5).

The agent has no calendar access. It writes a FreeBusyRequest to a stream the gateway
reads, and waits for the FreeBusyReply on a key named after the request. The reply holds
busy intervals only. No answer in time is "unavailable", never "free" (E1, E13).
"""

import logging
from typing import Protocol

from pydantic import ValidationError
from redis import Redis

from shared.messages import FreeBusyReply, FreeBusyRequest
from shared.streams import FREE_BUSY_REQUESTS, STREAM_MAX_LENGTH, free_busy_reply_key

logger = logging.getLogger(__name__)

REPLY_TIMEOUT_SECONDS = 20


class FreeBusyClient(Protocol):
    def ask(self, request: FreeBusyRequest) -> FreeBusyReply | None:
        """The reply, or None if the gateway did not answer in time or answered garbage."""
        ...


class RedisFreeBusyClient:
    def __init__(self, redis: Redis, timeout_seconds: int = REPLY_TIMEOUT_SECONDS) -> None:
        self._redis = redis
        self._timeout = timeout_seconds

    def ask(self, request: FreeBusyRequest) -> FreeBusyReply | None:
        self._redis.xadd(
            FREE_BUSY_REQUESTS,
            {"request": request.model_dump_json()},
            maxlen=STREAM_MAX_LENGTH,
            approximate=True,
        )
        popped = self._redis.blpop([free_busy_reply_key(request.request_id)], self._timeout)
        if popped is None:
            logger.warning("free/busy timed out: request_id=%s", request.request_id)
            return None
        try:
            reply = FreeBusyReply.model_validate_json(popped[1])
        except ValidationError:
            logger.warning("free/busy reply invalid: request_id=%s", request.request_id)
            return None
        if reply.request_id != request.request_id:
            return None
        return reply
