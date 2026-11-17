"""Logging in with Google: identity only (ADR-010, invariant 1, T16).

The login asks for `openid email` and nothing else: no refresh token, no Gmail, no
Calendar. The code exchange is one HTTPS call to Google's token endpoint with PKCE, and the
id_token is verified here (Google's signature, issuer, audience, expiry) before its email
is trusted. Gmail and Calendar are a separate consent, handled by google-gateway.
"""

import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx2
from google.auth import jwt
from pydantic import SecretStr

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - a public endpoint, not a secret
CERTS_URI = "https://www.googleapis.com/oauth2/v1/certs"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
SCOPES = "openid email"
CERTS_CACHE_SECONDS = 3600


class LoginError(Exception):
    """The exchange or the id_token failed. The message holds no token material."""


@dataclass(frozen=True)
class Identity:
    email: str
    email_verified: bool


class GoogleLogin(Protocol):
    def authorization_url(self, state: str, code_verifier: str) -> str: ...

    def exchange(self, code: str, code_verifier: str) -> Identity: ...


def code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class GoogleIdentityLogin:
    def __init__(self, client_id: str, client_secret: SecretStr, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._certs: dict[str, str] = {}
        self._certs_fetched = 0.0

    def authorization_url(self, state: str, code_verifier: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "code_challenge": code_challenge(code_verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{AUTH_URI}?{urlencode(params)}"

    def exchange(self, code: str, code_verifier: str) -> Identity:
        try:
            response = httpx2.post(
                TOKEN_URI,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret.get_secret_value(),
                    "redirect_uri": self._redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
                timeout=10,
            )
        except httpx2.HTTPError as exc:
            raise LoginError(type(exc).__name__) from None
        if response.status_code != 200:
            raise LoginError(f"token endpoint returned {response.status_code}")
        raw = response.json().get("id_token")
        if not isinstance(raw, str):
            raise LoginError("no id_token")
        return self._verify(raw)

    def _verify(self, raw: str) -> Identity:
        try:
            claims: dict[str, Any] = jwt.decode(
                raw, certs=self._google_certs(), audience=self._client_id
            )  # type: ignore[no-untyped-call]
        except ValueError as exc:
            raise LoginError("id_token rejected") from exc
        if claims.get("iss") not in ISSUERS:
            raise LoginError("id_token from an unexpected issuer")
        email = claims.get("email")
        if not isinstance(email, str):
            raise LoginError("id_token has no email")
        return Identity(email=email.lower(), email_verified=claims.get("email_verified") is True)

    def _google_certs(self) -> dict[str, str]:
        if not self._certs or time.monotonic() - self._certs_fetched > CERTS_CACHE_SECONDS:
            response = httpx2.get(CERTS_URI, timeout=10)
            response.raise_for_status()
            self._certs = dict(response.json())
            self._certs_fetched = time.monotonic()
        return self._certs
