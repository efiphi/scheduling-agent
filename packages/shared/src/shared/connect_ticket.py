"""A one-time ticket that hands "connect Google for this user" from the api to google-gateway.

The web app's "Connect Google" button cannot start the consent flow itself: the flow's
state and PKCE verifier belong to google-gateway, the only service that may hold Google
tokens (invariant 1, ADR-010). And the gateway has no sessions: it cannot tell who is
clicking. So:

1. The logged-in user asks the api (session + CSRF). The api puts a random ticket in Redis,
   holding only the user id and where to return, and answers with the gateway's start URL.
2. The browser opens that URL. The gateway takes the ticket (GETDEL: once, atomically),
   starts the consent flow for that user, and redirects to Google.
3. Google's callback reaches the gateway, never the api, and the gateway sends the browser
   back to the web app with only an outcome code.

The api never sees a Google token; the gateway never trusts a user id from the browser.
A ticket lives 5 minutes, is 256 random bits, and Redis holds only its SHA-256 as the key,
so a Redis dump has no usable ticket (T16).
"""

import hashlib
import re
import secrets
from typing import Literal, Protocol
from uuid import UUID

from shared.schema import StrictModel

TICKET_TTL_SECONDS = 300
_KEY_PREFIX = "google-connect-ticket:"
# secrets.token_urlsafe(32) gives 43 characters from this alphabet.
_TICKET_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}")

# Where the browser lands afterwards: a fixed list, so the redirect cannot be pointed
# anywhere else (an open redirect).
ReturnTo = Literal["onboarding", "settings/security"]


class ConnectTicket(StrictModel):
    user_id: UUID
    return_to: ReturnTo


class TicketRedis(Protocol):
    def set(self, name: str, value: str, *, ex: int, nx: bool) -> object: ...

    def getdel(self, name: str) -> object: ...


def _key(ticket: str) -> str:
    return _KEY_PREFIX + hashlib.sha256(ticket.encode()).hexdigest()


def issue(redis: TicketRedis, user_id: UUID, return_to: ReturnTo) -> str:
    ticket = secrets.token_urlsafe(32)
    stored = ConnectTicket(user_id=user_id, return_to=return_to).model_dump_json()
    if not redis.set(_key(ticket), stored, ex=TICKET_TTL_SECONDS, nx=True):
        raise RuntimeError("connect ticket already exists")
    return ticket


def redeem(redis: TicketRedis, ticket: str) -> ConnectTicket | None:
    """The ticket's content, once; None if malformed, unknown, expired or already used."""
    if not _TICKET_FORMAT.fullmatch(ticket):
        return None
    raw = redis.getdel(_key(ticket))
    if not isinstance(raw, bytes | str):
        return None
    return ConnectTicket.model_validate_json(raw)
