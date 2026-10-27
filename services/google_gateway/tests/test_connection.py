"""The connect flow's checks (connection.py), with fake Redis, Google and database."""

import logging
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from gateway_fakes import CODE, REFRESH_TOKEN, USER_EMAIL, FakeGoogle, FakeRepo, FakeStates, grant

from google_gateway.connection import ConnectFlow, Outcome
from google_gateway.google_oauth import SCOPES
from google_gateway.token_crypto import KEY_BYTES, TokenCipher

GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"


@dataclass
class Setup:
    flow: ConnectFlow
    states: FakeStates
    google: FakeGoogle
    repo: FakeRepo
    cipher: TokenCipher
    user_id: UUID

    def start(self) -> str:
        url = self.flow.start(self.user_id)
        return parse_qs(urlparse(url).query)["state"][0]


@pytest.fixture
def s() -> Setup:
    user_id = uuid4()
    states, google = FakeStates(), FakeGoogle()
    repo = FakeRepo(emails={user_id: USER_EMAIL})
    cipher = TokenCipher({1: bytes([7]) * KEY_BYTES})
    flow = ConnectFlow(states=states, google=google, repo=repo, cipher=cipher)
    return Setup(flow, states, google, repo, cipher, user_id)


def test_connects_and_stores_only_the_encrypted_refresh_token(s: Setup) -> None:
    assert s.flow.complete(s.start(), CODE, None) is Outcome.CONNECTED
    encrypted, scopes = s.repo.saved[s.user_id]
    assert REFRESH_TOKEN.encode() not in encrypted.data
    assert s.cipher.decrypt(encrypted, s.user_id) == REFRESH_TOKEN
    assert scopes == sorted(SCOPES)
    assert s.repo.audits[-1][1] == "google_connected"


def test_exchange_uses_the_verifier_stored_with_the_state(s: Setup) -> None:
    state = s.start()
    verifier = s.states.items[state].code_verifier
    s.flow.complete(state, CODE, None)
    assert s.google.exchanged == [(CODE, verifier)]


def test_each_start_gets_a_fresh_state_and_verifier(s: Setup) -> None:
    first, second = s.start(), s.start()
    assert first != second
    assert s.states.items[first].code_verifier != s.states.items[second].code_verifier


def test_state_works_only_once(s: Setup) -> None:
    state = s.start()
    assert s.flow.complete(state, CODE, None) is Outcome.CONNECTED
    assert s.flow.complete(state, CODE, None) is Outcome.INVALID_STATE
    assert len(s.google.exchanged) == 1


@pytest.mark.parametrize("state", [None, "", "forged-state-value"])
def test_callback_without_a_known_state_is_rejected_before_google(
    s: Setup, state: str | None
) -> None:
    # Login CSRF: an attacker sends the victim a callback link carrying the attacker's code.
    assert s.flow.complete(state, CODE, None) is Outcome.INVALID_STATE
    assert s.google.exchanged == []
    assert s.repo.saved == {}
    assert s.repo.security_events == [(None, "oauth_invalid_state", {})]


def test_user_declining_consent_stores_nothing(s: Setup) -> None:
    assert s.flow.complete(s.start(), None, "access_denied") is Outcome.DECLINED
    assert s.google.exchanged == []
    assert s.repo.saved == {}
    assert s.repo.security_events == []


def test_failed_exchange_is_a_security_event_without_the_error_text(s: Setup) -> None:
    s.google.result = ValueError(f"invalid_grant for code {CODE}")
    assert s.flow.complete(s.start(), CODE, None) is Outcome.EXCHANGE_FAILED
    assert s.repo.security_events == [(s.user_id, "oauth_exchange_failed", {"error": "ValueError"})]


def test_t18_missing_scope_is_rejected(s: Setup) -> None:
    # Google's consent screen lets the user untick a permission.
    s.google.result = grant(scopes=SCOPES - {GMAIL_SEND})
    assert s.flow.complete(s.start(), CODE, None) is Outcome.WRONG_SCOPES
    assert s.repo.saved == {}
    assert s.repo.audits[-1][2] == {"missing": [GMAIL_SEND], "unexpected": []}


def test_t18_extra_scope_is_rejected(s: Setup) -> None:
    extra = "https://mail.google.com/"
    s.google.result = grant(scopes=SCOPES | {extra})
    assert s.flow.complete(s.start(), CODE, None) is Outcome.WRONG_SCOPES
    assert s.repo.saved == {}
    assert s.repo.audits[-1][2] == {"missing": [], "unexpected": [extra]}


@pytest.mark.parametrize(
    "changes",
    [
        {"email": "someone-else@example.com"},
        {"email_verified": False},
        {"email": None},
    ],
)
def test_t16_a_different_google_account_is_rejected(s: Setup, changes: dict[str, object]) -> None:
    s.google.result = grant(**changes)
    assert s.flow.complete(s.start(), CODE, None) is Outcome.WRONG_ACCOUNT
    assert s.repo.saved == {}
    assert s.repo.security_events == [(s.user_id, "google_account_mismatch", {})]


def test_account_email_comparison_ignores_case(s: Setup) -> None:
    s.google.result = grant(email=USER_EMAIL.upper())
    assert s.flow.complete(s.start(), CODE, None) is Outcome.CONNECTED


def test_no_refresh_token_is_rejected(s: Setup) -> None:
    s.google.result = grant(refresh_token=None)
    assert s.flow.complete(s.start(), CODE, None) is Outcome.NO_REFRESH_TOKEN
    assert s.repo.saved == {}


def test_user_deleted_between_start_and_callback(s: Setup) -> None:
    state = s.start()
    s.repo.emails.clear()
    assert s.flow.complete(state, CODE, None) is Outcome.UNKNOWN_USER
    assert s.repo.saved == {}


def test_t22_logs_never_contain_the_code_state_verifier_or_token(
    s: Setup, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    state = s.start()
    verifier = s.states.items[state].code_verifier
    s.flow.complete(state, CODE, None)
    s.google.result = RuntimeError(f"bad {CODE} {REFRESH_TOKEN}")
    s.flow.complete(s.start(), CODE, None)
    assert "outcome=connected" in caplog.text
    for secret in (CODE, state, verifier, REFRESH_TOKEN):
        assert secret not in caplog.text
    assert str(s.repo.audits).count(REFRESH_TOKEN) == 0
    assert REFRESH_TOKEN not in repr(grant())
