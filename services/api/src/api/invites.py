"""Invite links: making them, and keeping the token out of every log and trace (UC-A1, T14).

The link is `<web app>/invite#<token>`. The token sits after `#`, the URL fragment, which
browsers never send to a server: it cannot land in Traefik's or nginx's logs, in a
Referer header, or in a trace's http.url. The web app reads it from the fragment and posts
it in a JSON body to the api, where the body is never logged either (T22).

The database stores only the token's SHA-256 (migration 0007). A token is 256 random bits,
so guessing one is not a practical attack; it also works once, for one address, for 72
hours.
"""

import hashlib
import re
import secrets
from datetime import timedelta

from pydantic import Field

from shared.schema import StrictModel

INVITE_LIFETIME = timedelta(hours=72)

# Deliberately simple: Google decides what a real address is. This only keeps junk out.
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$"


def new_invite_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_link(web_app_url: str, token: str) -> str:
    return f"{web_app_url.rstrip('/')}/invite#{token}"


def email_hint(email: str) -> str:
    """dana@example.com -> d***@example.com: enough to recognise, not enough to harvest."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def valid_email(email: str) -> bool:
    return re.fullmatch(EMAIL_PATTERN, email) is not None


class InviteTokenIn(StrictModel):
    token: str = Field(min_length=20, max_length=100)


class InviteCreateIn(StrictModel):
    email: str = Field(max_length=254)
