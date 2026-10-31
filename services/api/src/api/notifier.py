"""The api process that tells users about new pending actions on WhatsApp (step 1b-2).

    python -m api.notifier

google-gateway puts only (user_id, action_id) on the notifications stream; this process
reads the action from the database itself, as the api's role under the user's RLS
context, before anything is sent. The api is the only holder of the Meta token.
"""

import logging
import socket
import time
from typing import Any
from uuid import UUID

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from api.whatsapp import Notifier
from shared import log, tracing
from shared.streams import NOTIFICATIONS

logger = logging.getLogger(__name__)
_tracer = tracing.tracer(__name__)
GROUP = "api"
BLOCK_MS = 5_000


def ensure_group(redis: Redis) -> None:
    try:
        redis.xgroup_create(NOTIFICATIONS, GROUP, id="0", mkstream=True)
    except ResponseError as error:
        if "BUSYGROUP" not in str(error):
            raise


def run_once(redis: Redis, notifier: Notifier, consumer: str) -> int:
    response: Any = redis.xreadgroup(GROUP, consumer, {NOTIFICATIONS: ">"}, count=1, block=BLOCK_MS)
    if not response:
        return 0
    message_id, fields = response[0][1][0]
    try:
        user_id = UUID(fields[b"user_id"].decode())
        action_id = UUID(fields[b"action_id"].decode())
    except (KeyError, ValueError):
        logger.error("invalid notification dropped")
    else:
        with _tracer.start_as_current_span(
            "notification.send", context=tracing.extract(fields)
        ) as span:
            try:
                outcome = notifier.notify(user_id, action_id)
            except Exception as exc:  # a failed notification must not block the queue
                outcome = f"error_{type(exc).__name__}"
            span.set_attribute("notification.outcome", outcome)
        logger.info("notification handled: action_id=%s outcome=%s", action_id, outcome)
    redis.xack(NOTIFICATIONS, GROUP, message_id)
    return 1


def main() -> None:
    from api.wiring import deps_from_env

    # JSON lines with the trace id; quiet HTTP clients and redaction (shared.log, T22).
    log.configure("notifier")
    tracing.configure("notifier")
    deps = deps_from_env()
    if deps.whatsapp is None or deps.notifier is None:
        raise SystemExit("WhatsApp is not configured (see deploy/compose/.env.example)")
    ensure_group(deps.redis)
    while True:
        try:
            run_once(deps.redis, deps.notifier, socket.gethostname())
        except (RedisTimeoutError, RedisConnectionError) as exc:
            # A Redis hiccup is not a reason to die; unacknowledged work is retried.
            logger.warning("redis unavailable, retrying: error=%s", type(exc).__name__)
            time.sleep(1)


if __name__ == "__main__":
    main()
