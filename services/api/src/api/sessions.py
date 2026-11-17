"""Login state and sessions, kept in Redis (docs/04-web-app.md, T10, T11).

Login state: a random `state` plus the PKCE verifier, single-use (GETDEL), 10 minutes, so
a forged callback cannot log the victim into the attacker's account (login CSRF).

Sessions:
- The browser holds only a random 256-bit session id, in an HttpOnly, Secure, SameSite
  cookie: page scripts cannot read it.
- Redis holds the session under the SHA-256 of that id, so a Redis dump does not contain
  usable session ids.
- Idle timeout 30 minutes (each request extends it) and an absolute limit of 12 hours.
- Each session has its own CSRF token. Every request that changes something must send it
  in a header; another site can make the browser send the cookie, but cannot read the token.
- All of a user's sessions are indexed, so "log out everywhere" is one call.
"""

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from redis import Redis

from shared.schema import StrictModel

LOGIN_STATE_SECONDS = 600
IDLE_SECONDS = 30 * 60
ABSOLUTE_SECONDS = 12 * 3600


class LoginState(StrictModel):
    code_verifier: str


class SessionData(StrictModel):
    user_id: UUID
    csrf_token: str
    created_at: float
    authenticated_at: float  # for "log in again" before sensitive actions


@dataclass(frozen=True)
class Session:
    session_id: str
    data: SessionData


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class SessionStore(Protocol):
    def put_login_state(self, state: str, login: LoginState) -> None: ...

    def take_login_state(self, state: str) -> LoginState | None: ...

    def create(self, user_id: UUID) -> Session: ...

    def get(self, session_id: str) -> Session | None: ...

    def delete(self, session_id: str) -> None: ...

    def delete_all(self, user_id: UUID) -> int: ...


class RedisSessionStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def put_login_state(self, state: str, login: LoginState) -> None:
        self._redis.set(
            f"login-state:{_digest(state)}",
            login.model_dump_json(),
            ex=LOGIN_STATE_SECONDS,
            nx=True,
        )

    def take_login_state(self, state: str) -> LoginState | None:
        raw = self._redis.getdel(f"login-state:{_digest(state)}")
        return None if raw is None else LoginState.model_validate_json(raw)

    def create(self, user_id: UUID) -> Session:
        session_id, now = new_token(), time.time()
        data = SessionData(
            user_id=user_id, csrf_token=new_token(), created_at=now, authenticated_at=now
        )
        key = f"session:{_digest(session_id)}"
        pipe = self._redis.pipeline()
        pipe.set(key, data.model_dump_json(), ex=IDLE_SECONDS)
        pipe.sadd(f"user-sessions:{user_id}", key)
        pipe.expire(f"user-sessions:{user_id}", ABSOLUTE_SECONDS)
        pipe.execute()
        return Session(session_id, data)

    def get(self, session_id: str) -> Session | None:
        if not session_id or len(session_id) > 100:
            return None
        key = f"session:{_digest(session_id)}"
        raw = self._redis.get(key)
        if raw is None:
            return None
        data = SessionData.model_validate_json(raw)
        if time.time() - data.created_at > ABSOLUTE_SECONDS:
            self._redis.delete(key)
            return None
        self._redis.expire(key, IDLE_SECONDS)  # sliding idle timeout
        return Session(session_id, data)

    def delete(self, session_id: str) -> None:
        self._redis.delete(f"session:{_digest(session_id)}")

    def delete_all(self, user_id: UUID) -> int:
        index = f"user-sessions:{user_id}"
        keys = [k.decode() if isinstance(k, bytes) else str(k) for k in self._redis.smembers(index)]
        if keys:
            self._redis.delete(*keys)
        self._redis.delete(index)
        return len(keys)
