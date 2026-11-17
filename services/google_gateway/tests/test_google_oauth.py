"""The real Google client's URL and token handling, without network access."""

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from google_auth_oauthlib.flow import Flow
from pydantic import SecretStr

from google_gateway.google_oauth import SCOPES, FlowOAuthClient
from google_gateway.oauth_state import new_code_verifier, new_state

REDIRECT = "http://localhost:8001/oauth/google/callback"


def client() -> FlowOAuthClient:
    return FlowOAuthClient(
        "synthetic-client-id.apps.googleusercontent.com", SecretStr("synthetic"), REDIRECT
    )


def test_consent_url_asks_for_exactly_what_we_need() -> None:
    state, verifier = new_state(), new_code_verifier()
    url = client().authorization_url(state, verifier)
    params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith("https://accounts.google.com/")
    assert params["state"] == state
    assert params["redirect_uri"] == REDIRECT
    assert set(params["scope"].split()) == SCOPES
    assert params["access_type"] == "offline"
    assert params["prompt"] == "consent"
    # PKCE: only the hash of the verifier goes to the browser.
    assert params["code_challenge_method"] == "S256"
    assert verifier not in url
    # Never fold in scopes granted earlier: the grant must be exactly SCOPES (T18).
    assert "include_granted_scopes" not in params


def test_t18_gmail_delete_and_full_access_scopes_are_never_requested() -> None:
    for broad in (
        "https://mail.google.com/",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
    ):
        assert broad not in SCOPES


def test_partial_grant_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    # oauthlib raises a Warning when the granted scopes differ from the requested ones.
    granted = sorted(SCOPES - {"https://www.googleapis.com/auth/gmail.send"})

    def fetch_token(self: Any, **_: Any) -> dict[str, Any]:
        changed = Warning("Scope has changed")
        changed.token = {"access_token": "a", "scope": granted, "id_token": None}  # type: ignore[attr-defined]
        raise changed

    monkeypatch.setattr(Flow, "fetch_token", fetch_token)
    result = client().exchange("code", new_code_verifier())
    assert result.scopes == frozenset(granted)
    assert result.refresh_token is None
    assert result.email is None
