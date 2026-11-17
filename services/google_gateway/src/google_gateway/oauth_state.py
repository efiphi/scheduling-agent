"""Short-lived, single-use OAuth `state` values in Redis.

`state` ties Google's redirect back to a connection this gateway started, so an attacker
cannot make the callback store *their* Google account under a victim's user (login CSRF).
Each value:
- is random (256 bits), so it cannot be guessed;
- lives 10 minutes, so an abandoned link stops working;
- is read with GETDEL, an atomic read-and-delete, so it works once even if two requests
  race with the same value (replay).
It also carries the PKCE code_verifier: Google only issues tokens to whoever presents the
verifier, so an intercepted authorization code is useless on its own.
"""

import re
import secrets
from typing import Protocol
from uuid import UUID

from redis import Redis

from shared.schema import StrictModel

STATE_TTL_SECONDS = 600
_KEY_PREFIX = "oauth-state:"
# secrets.token_urlsafe(32) gives 43 characters from this alphabet.
_STATE_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}")


class PendingConnect(StrictModel):
    user_id: UUID
    code_verifier: str


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    # 86 characters; PKCE allows 43 to 128 (RFC 7636).
    return secrets.token_urlsafe(64)


class StateStore(Protocol):
    def put(self, state: str, pending: PendingConnect) -> None: ...

    def take(self, state: str) -> PendingConnect | None:
        """Return and delete the pending connection, or None if unknown, expired or used."""
        ...


class RedisStateStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def put(self, state: str, pending: PendingConnect) -> None:
        # nx: never overwrite an existing state (a collision would be a bug, not a retry).
        stored = self._redis.set(
            _KEY_PREFIX + state, pending.model_dump_json(), ex=STATE_TTL_SECONDS, nx=True
        )
        if not stored:
            raise RuntimeError("OAuth state already exists")

    def take(self, state: str) -> PendingConnect | None:
        if not _STATE_FORMAT.fullmatch(state):
            return None
        raw = self._redis.getdel(_KEY_PREFIX + state)
        if raw is None:
            return None
        return PendingConnect.model_validate_json(raw)
