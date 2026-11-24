"""Joining by invite, end to end through the api with fakes (UC-A1, UC-A6, T14, T22)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from api_fakes import FakeLogin, FakeRedis, FakeSessions, FakeStore
from fastapi.testclient import TestClient

from api.google_login import Identity
from api.invites import email_hint, token_hash
from api.main import COOKIE, Deps, create_app

ADMIN = "admin@example.com"
INVITEE = "new-member@example.com"
APP = "https://agent.example/"


@dataclass
class Setup:
    client: TestClient
    login: FakeLogin
    sessions: FakeSessions
    store: FakeStore
    admin: UUID

    def log_in_as(self, email: str) -> str:
        """Log in through the normal flow; returns the CSRF token."""
        self.login.identity = Identity(email, True)
        redirect = self.client.get("/auth/google/login", follow_redirects=False)
        self.client.get(
            "/auth/google/callback",
            params={"state": _state(redirect.headers["location"]), "code": "c"},
            follow_redirects=False,
        )
        return str(self.client.get("/me").json()["csrf_token"])

    def invite(self, email: str = INVITEE) -> str:
        """The admin invites; returns the token taken from the link's fragment."""
        csrf = self.log_in_as(ADMIN)
        made = self.client.post("/admin/invites", json={"email": email}, headers=_h(csrf))
        assert made.status_code == 201, made.text
        self.client.cookies.clear()
        return str(made.json()["link"]).split("#", 1)[1]

    def accept(self, token: str, email: str = INVITEE) -> str:
        """The invitee opens the link and logs in; returns where the callback sent them."""
        self.login.identity = Identity(email, True)
        start = self.client.post("/auth/google/invite", json={"token": token})
        assert start.status_code == 200, start.text
        done = self.client.get(
            "/auth/google/callback",
            params={"state": _state(start.json()["url"]), "code": "c"},
            follow_redirects=False,
        )
        return str(done.headers["location"])


def _state(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def _h(csrf: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf}


@pytest.fixture
def s() -> Setup:
    login, sessions, store = FakeLogin(), FakeSessions(), FakeStore()
    admin = store.add_user(ADMIN, is_admin=True)
    deps = Deps(
        login=login,
        sessions=sessions,
        store=store,
        redis=FakeRedis(),  # type: ignore[arg-type]
        web_app_url=APP,
        cookie_secure=True,
    )
    client = TestClient(create_app(deps), base_url="https://testserver")
    return Setup(client, login, sessions, store, admin)


# --- Making an invite ---------------------------------------------------------------------


def test_t22_the_token_is_in_the_fragment_and_only_its_hash_is_stored(s: Setup) -> None:
    token = s.invite()
    assert len(token) >= 40  # 256 random bits
    assert token not in s.store.invite_rows  # stored by hash only
    assert token_hash(token) in s.store.invite_rows


def test_t14_an_ordinary_user_cannot_invite(s: Setup) -> None:
    s.store.add_user("member@example.com")
    csrf = s.log_in_as("member@example.com")
    made = s.client.post("/admin/invites", json={"email": INVITEE}, headers=_h(csrf))
    assert made.status_code == 403
    assert s.store.invite_rows == {}


def test_inviting_needs_the_csrf_token(s: Setup) -> None:
    s.log_in_as(ADMIN)
    assert s.client.post("/admin/invites", json={"email": INVITEE}).status_code == 403


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "two@@example.com"])
def test_junk_addresses_are_refused(s: Setup, email: str) -> None:
    csrf = s.log_in_as(ADMIN)
    made = s.client.post("/admin/invites", json={"email": email}, headers=_h(csrf))
    assert made.status_code == 422


def test_an_existing_user_is_not_invited_again(s: Setup) -> None:
    csrf = s.log_in_as(ADMIN)
    made = s.client.post("/admin/invites", json={"email": ADMIN.upper()}, headers=_h(csrf))
    assert made.status_code == 409


# --- Opening the link -------------------------------------------------------------------


def test_the_link_shows_only_a_hint_of_the_address(s: Setup) -> None:
    token = s.invite()
    checked = s.client.post("/invites/check", json={"token": token})
    assert checked.json() == {"email_hint": "n***@example.com"}
    assert email_hint("dana@example.org") == "d***@example.org"


def test_t14_unknown_invites_all_look_the_same(s: Setup) -> None:
    for token in ("x" * 43, "y" * 43):
        assert s.client.post("/invites/check", json={"token": token}).status_code == 404
        assert s.client.post("/auth/google/invite", json={"token": token}).status_code == 404


def test_the_invite_login_suggests_the_invited_account(s: Setup) -> None:
    token = s.invite()
    s.client.post("/auth/google/invite", json={"token": token})
    assert s.login.hints[-1] == INVITEE


# --- Accepting ------------------------------------------------------------------------------


def test_t14_accepting_creates_the_user_and_starts_onboarding(s: Setup) -> None:
    token = s.invite()
    assert s.accept(token) == "https://agent.example/onboarding"
    me = s.client.get("/me").json()
    assert me["email"] == INVITEE
    assert me["is_admin"] is False


def test_t14_an_invite_works_once(s: Setup) -> None:
    token = s.invite()
    s.accept(token)
    s.client.cookies.clear()
    assert s.client.post("/auth/google/invite", json={"token": token}).status_code == 404


def test_t14_logging_in_with_another_account_is_refused(s: Setup) -> None:
    token = s.invite()
    assert s.accept(token, "someone-else@example.com").endswith("/login?error=not_invited")
    assert s.client.get("/me").status_code == 401
    # The refusal did not use the invite up: the right account can still join.
    assert s.accept(token).endswith("/onboarding")


def test_t14_an_unverified_google_address_is_refused(s: Setup) -> None:
    token = s.invite()
    s.login.identity = Identity(INVITEE, False)
    start = s.client.post("/auth/google/invite", json={"token": token})
    done = s.client.get(
        "/auth/google/callback",
        params={"state": _state(start.json()["url"]), "code": "c"},
        follow_redirects=False,
    )
    assert done.headers["location"].endswith("/login?error=not_invited")
    assert COOKIE not in done.headers.get("set-cookie", "")


def test_t14_an_expired_invite_is_refused(s: Setup) -> None:
    token = s.invite()
    admin, invite = s.store.invite_rows[token_hash(token)]
    past = datetime.now(UTC) - timedelta(minutes=1)
    expired = type(invite)(**{**invite.__dict__, "expires_at": past})
    s.store.invite_rows[token_hash(token)] = (admin, expired)
    assert s.client.post("/auth/google/invite", json={"token": token}).status_code == 404


def test_t14_a_revoked_invite_is_refused(s: Setup) -> None:
    token = s.invite()
    csrf = s.log_in_as(ADMIN)
    invite_id = s.client.get("/admin/invites").json()[0]["invite_id"]
    assert s.client.delete(f"/admin/invites/{invite_id}", headers=_h(csrf)).status_code == 200
    s.client.cookies.clear()
    assert s.client.post("/invites/check", json={"token": token}).status_code == 404


def test_t14_a_normal_login_never_accepts_an_invite(s: Setup) -> None:
    s.invite()
    s.login.identity = Identity(INVITEE, True)
    redirect = s.client.get("/auth/google/login", follow_redirects=False)
    done = s.client.get(
        "/auth/google/callback",
        params={"state": _state(redirect.headers["location"]), "code": "c"},
        follow_redirects=False,
    )
    assert done.headers["location"].endswith("/login?error=not_invited")


# --- The admin's lists ----------------------------------------------------------------------


def test_admin_sees_invites_and_users(s: Setup) -> None:
    token = s.invite()
    s.accept(token)
    s.client.cookies.clear()
    s.log_in_as(ADMIN)
    invites = s.client.get("/admin/invites").json()
    assert [(i["email"], i["status"]) for i in invites] == [(INVITEE, "used")]
    assert "link" not in invites[0]  # the link is shown once, when it is made
    users = {u["email"] for u in s.client.get("/admin/users").json()}
    assert users == {ADMIN, INVITEE}


def test_ordinary_users_get_no_admin_lists(s: Setup) -> None:
    s.store.add_user("member@example.com")
    s.log_in_as("member@example.com")
    assert s.client.get("/admin/users").status_code == 403
    assert s.client.get("/admin/invites").status_code == 403
