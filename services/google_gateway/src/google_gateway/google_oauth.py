"""The Google side of the connect flow: build the consent URL, exchange the code for tokens.

Only google-gateway talks to Google (invariant 1). This module returns what Google granted
and leaves every decision (scopes, account, storage) to connection.py, so tests can swap
in a fake client without network access.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

import google.oauth2.credentials
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from pydantic import SecretStr

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - a public endpoint, not a secret

# Every scope and why (invariant 6, T18). Full URLs, because that is how Google reports
# granted scopes and they are compared exactly. No Gmail delete or modify, no full Calendar.
SCOPES: frozenset[str] = frozenset(
    {
        "openid",  # an id_token that says which account consented
        "https://www.googleapis.com/auth/userinfo.email",  # that account's email, to match it
        "https://www.googleapis.com/auth/gmail.readonly",  # read incoming meeting requests
        "https://www.googleapis.com/auth/gmail.send",  # send approved replies
        # Read, create, change and cancel events on calendars the user owns. Free/busy is
        # computed from these events (step 1.7). Every cancellation needs approval.
        "https://www.googleapis.com/auth/calendar.events.owned",
    }
)


@dataclass(frozen=True)
class GoogleGrant:
    """What Google returned. The refresh token is kept out of repr so it never reaches a log."""

    refresh_token: str | None = field(repr=False)
    scopes: frozenset[str]
    email: str | None
    email_verified: bool


class GoogleOAuthClient(Protocol):
    def authorization_url(self, state: str, code_verifier: str) -> str: ...

    def exchange(self, code: str, code_verifier: str) -> GoogleGrant: ...


class FlowOAuthClient:
    """The real client, built on google-auth-oauthlib's Flow."""

    def __init__(self, client_id: str, client_secret: SecretStr, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def _flow(self, code_verifier: str) -> Flow:
        config = {
            "web": {
                "client_id": self._client_id,
                "client_secret": self._client_secret.get_secret_value(),
                "auth_uri": AUTH_URI,
                "token_uri": TOKEN_URI,
            }
        }
        return Flow.from_client_config(
            config,
            scopes=sorted(SCOPES),
            redirect_uri=self._redirect_uri,
            code_verifier=code_verifier,
            autogenerate_code_verifier=False,
        )

    def authorization_url(self, state: str, code_verifier: str) -> str:
        # Flow adds the PKCE challenge (S256) computed from code_verifier.
        url, _ = self._flow(code_verifier).authorization_url(
            state=state,
            access_type="offline",  # ask for a refresh token: the agent works while you're away
            prompt="consent",  # always show consent, so Google always returns a refresh token
        )
        return str(url)

    def exchange(self, code: str, code_verifier: str) -> GoogleGrant:
        try:
            token: dict[str, Any] = dict(self._flow(code_verifier).fetch_token(code=code))
        except Warning as changed:
            # oauthlib raises a Warning when Google granted different scopes than requested
            # (the user unticked a box). Keep the token response and let connection.py
            # reject it with a clear reason, instead of failing with a library error.
            token = dict(changed.token)  # type: ignore[attr-defined]
        claims = self._verify_id_token(token.get("id_token"))
        return GoogleGrant(
            refresh_token=token.get("refresh_token"),
            scopes=_scope_set(token.get("scope", ())),
            email=claims.get("email"),
            email_verified=claims.get("email_verified") is True,
        )

    def _verify_id_token(self, raw: object) -> dict[str, Any]:
        if not isinstance(raw, str):
            return {}
        # Checks Google's signature, the issuer, the expiry, and that it was issued to
        # this client (audience), so a token minted for another app is rejected.
        claims: dict[str, Any] = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            raw, Request(), audience=self._client_id
        )
        return claims

    def credentials(self, refresh_token: str) -> google.oauth2.credentials.Credentials:
        """Credentials that fetch a fresh access token on first use. Memory only (ADR-016)."""
        return google.oauth2.credentials.Credentials(  # type: ignore[no-untyped-call]
            None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=self._client_id,
            client_secret=self._client_secret.get_secret_value(),
            scopes=sorted(SCOPES),
        )


def _scope_set(scope: str | Iterable[str]) -> frozenset[str]:
    if isinstance(scope, str):
        return frozenset(scope.split())
    return frozenset(scope)
