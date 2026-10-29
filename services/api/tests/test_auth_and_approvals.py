"""Login, sessions, CSRF and approvals in the api (T10, T13, T14, T16), with fakes."""

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from api_fakes import HASH, USER_EMAIL, FakeLogin, FakeRedis, FakeSessions, FakeStore
from fastapi.testclient import TestClient

from api.google_login import Identity, LoginError
from api.main import COOKIE, Deps, create_app
from shared.streams import APPROVED_ACTIONS


@dataclass
class Setup:
    client: TestClient
    login: FakeLogin
    sessions: FakeSessions
    store: FakeStore
    redis: FakeRedis
    user: UUID

    def log_in(self) -> str:
        """Walks the real login flow; returns the CSRF token."""
        redirect = self.client.get("/auth/google/login", follow_redirects=False)
        state = parse_qs(urlparse(redirect.headers["location"]).query)["state"][0]
        done = self.client.get(
            "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
        )
        assert done.status_code == 303
        return str(self.client.get("/me").json()["csrf_token"])


@pytest.fixture
def s() -> Setup:
    login, sessions, store, redis = FakeLogin(), FakeSessions(), FakeStore(), FakeRedis()
    user = store.add_user()
    deps = Deps(
        login=login,
        sessions=sessions,
        store=store,
        redis=redis,  # type: ignore[arg-type]
        web_app_url="http://localhost:5173/",
        cookie_secure=True,
    )
    return Setup(
        TestClient(create_app(deps), base_url="https://testserver"),
        login,
        sessions,
        store,
        redis,
        user,
    )


# --- Login ------------------------------------------------------------------------------


def test_login_sets_a_locked_down_session_cookie_and_returns_to_the_app(s: Setup) -> None:
    redirect = s.client.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(redirect.headers["location"]).query)["state"][0]
    done = s.client.get(
        "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert done.headers["location"] == "http://localhost:5173/"
    cookie = done.headers["set-cookie"].lower()
    for flag in ("httponly", "secure", "samesite=lax"):
        assert flag in cookie
    assert (s.user, "login") in s.store.audits


def test_login_state_works_once(s: Setup) -> None:
    redirect = s.client.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(redirect.headers["location"]).query)["state"][0]
    s.client.get(
        "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    again = s.client.get(
        "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert again.status_code == 400
    assert len(s.login.exchanged) == 1


@pytest.mark.parametrize(
    "params", [{}, {"state": "forged", "code": "c"}, {"error": "access_denied"}]
)
def test_login_csrf_a_callback_we_did_not_start_is_refused(
    s: Setup, params: dict[str, str]
) -> None:
    response = s.client.get("/auth/google/callback", params=params, follow_redirects=False)
    assert response.status_code == 400
    assert COOKIE not in response.headers.get("set-cookie", "")
    assert s.login.exchanged == []


@pytest.mark.parametrize(
    "identity",
    [Identity("stranger@example.org", True), Identity(USER_EMAIL, False), LoginError("rejected")],
)
def test_t14_only_invited_verified_accounts_get_in(
    s: Setup, identity: Identity | LoginError
) -> None:
    s.login.identity = identity
    redirect = s.client.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(redirect.headers["location"]).query)["state"][0]
    response = s.client.get(
        "/auth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False
    )
    assert response.status_code in (400, 403)
    assert s.sessions.sessions == {}


def test_without_a_session_everything_is_401(s: Setup) -> None:
    assert s.client.get("/me").status_code == 401
    assert s.client.get("/actions").status_code == 401


def test_logout_ends_the_session(s: Setup) -> None:
    csrf = s.log_in()
    assert s.client.post("/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert s.client.get("/me").status_code == 401


def test_t11_log_out_everywhere(s: Setup) -> None:
    csrf = s.log_in()
    s.sessions.create(s.user)  # another device
    assert s.client.delete("/sessions", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert s.sessions.sessions == {}


# --- Approvals --------------------------------------------------------------------------


def test_pending_actions_show_the_full_email(s: Setup) -> None:
    s.log_in()
    action = s.store.add_action(s.user)
    [shown] = s.client.get("/actions").json()
    assert shown["action_id"] == str(action)
    assert shown["to"] == ["dana@example.org"] and shown["content_hash"] == HASH


def test_approval_records_and_hands_the_action_to_the_gateway(s: Setup) -> None:
    csrf = s.log_in()
    action = s.store.add_action(s.user)
    response = s.client.post(
        f"/actions/{action}/approve", json={"content_hash": HASH}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200
    assert s.redis.streams[APPROVED_ACTIONS] == [{"action_id": str(action), "user_id": str(s.user)}]


@pytest.mark.parametrize("headers", [{}, {"X-CSRF-Token": "wrong"}])
def test_t10_approval_without_the_csrf_token_is_refused(s: Setup, headers: dict[str, str]) -> None:
    # A page on another site can make the browser send the cookie, not the token.
    s.log_in()
    action = s.store.add_action(s.user)
    response = s.client.post(
        f"/actions/{action}/approve", json={"content_hash": HASH}, headers=headers
    )
    assert response.status_code == 403
    assert s.store.approvals == set()


def test_t10_approval_twice_is_refused(s: Setup) -> None:
    csrf = s.log_in()
    action = s.store.add_action(s.user)
    first = s.client.post(
        f"/actions/{action}/approve", json={"content_hash": HASH}, headers={"X-CSRF-Token": csrf}
    )
    second = s.client.post(
        f"/actions/{action}/approve", json={"content_hash": HASH}, headers={"X-CSRF-Token": csrf}
    )
    assert (first.status_code, second.status_code) == (200, 409)
    assert len(s.redis.streams[APPROVED_ACTIONS]) == 1


def test_t3_approval_for_different_content_is_refused(s: Setup) -> None:
    csrf = s.log_in()
    action = s.store.add_action(s.user)
    response = s.client.post(
        f"/actions/{action}/approve",
        json={"content_hash": "sha256:" + "b" * 64},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 409 and response.json()["detail"] == "hash_mismatch"


def test_e7_an_expired_action_cannot_be_approved(s: Setup) -> None:
    csrf = s.log_in()
    action = s.store.add_action(s.user, expires_in=timedelta(minutes=-1))
    response = s.client.post(
        f"/actions/{action}/approve", json={"content_hash": HASH}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 409 and response.json()["detail"] == "expired"


def test_t13_another_users_action_looks_like_it_does_not_exist(s: Setup) -> None:
    csrf = s.log_in()
    other = s.store.add_user("other@example.org")
    theirs = s.store.add_action(other)
    assert s.client.get(f"/actions/{theirs}").status_code == 404
    response = s.client.post(
        f"/actions/{theirs}/approve", json={"content_hash": HASH}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 404


def test_a_paused_agent_cannot_approve(s: Setup) -> None:
    csrf = s.log_in()
    action = s.store.add_action(s.user)
    user = s.store.users[s.user]
    s.store.users[s.user] = user.__class__(user.user_id, user.email, "paused", user.is_admin)
    response = s.client.post(
        f"/actions/{action}/approve", json={"content_hash": HASH}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 409


def test_reject(s: Setup) -> None:
    csrf = s.log_in()
    action = s.store.add_action(s.user)
    assert (
        s.client.post(f"/actions/{action}/reject", headers={"X-CSRF-Token": csrf}).status_code
        == 200
    )
    assert (
        s.client.post(f"/actions/{action}/reject", headers={"X-CSRF-Token": csrf}).status_code
        == 404
    )
