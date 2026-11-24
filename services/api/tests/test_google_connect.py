"""Connecting Google from the web app: the api hands out a ticket and never a token (T16)."""

from urllib.parse import parse_qs, urlparse

import pytest
from api_fakes import USER_EMAIL, FakeLogin, FakeRedis, FakeSessions, FakeStore
from fastapi.testclient import TestClient

from api.main import Deps, create_app
from shared import connect_ticket

START = "https://agent.example/oauth/google/start"


@pytest.fixture
def setup() -> tuple[TestClient, FakeStore, FakeRedis]:
    store, redis = FakeStore(), FakeRedis()
    store.add_user(USER_EMAIL)
    deps = Deps(
        login=FakeLogin(),
        sessions=FakeSessions(),
        store=store,
        redis=redis,  # type: ignore[arg-type]
        web_app_url="https://agent.example/",
        cookie_secure=True,
        connect_start_url=START,
    )
    return TestClient(create_app(deps), base_url="https://testserver"), store, redis


def log_in(client: TestClient) -> str:
    redirect = client.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(redirect.headers["location"]).query)["state"][0]
    client.get("/auth/google/callback", params={"state": state, "code": "c"})
    return str(client.get("/me").json()["csrf_token"])


def test_t16_connect_returns_a_one_time_ticket_for_the_gateway(
    setup: tuple[TestClient, FakeStore, FakeRedis],
) -> None:
    client, store, redis = setup
    csrf = log_in(client)
    answer = client.post(
        "/integrations/google/connect",
        json={"return_to": "settings/security"},
        headers={"X-CSRF-Token": csrf},
    )
    url = answer.json()["url"]
    assert url.startswith(f"{START}?ticket=")
    ticket = parse_qs(urlparse(url).query)["ticket"][0]
    found = connect_ticket.redeem(redis, ticket)
    assert found is not None
    assert found.user_id == next(iter(store.users))
    assert found.return_to == "settings/security"


def test_connect_needs_the_csrf_token_and_a_known_screen(
    setup: tuple[TestClient, FakeStore, FakeRedis],
) -> None:
    client, _, redis = setup
    csrf = log_in(client)
    assert client.post("/integrations/google/connect", json={}).status_code == 403
    bad = client.post(
        "/integrations/google/connect",
        json={"return_to": "https://evil.example/"},
        headers={"X-CSRF-Token": csrf},
    )
    assert bad.status_code == 422  # no open redirect
    assert redis.values == {}


def test_me_reports_the_setup_state(setup: tuple[TestClient, FakeStore, FakeRedis]) -> None:
    client, store, _ = setup
    log_in(client)
    me = client.get("/me").json()
    assert (me["google_status"], me["whatsapp_verified"]) == ("not_connected", False)
    store.google[next(iter(store.users))] = "connected"
    assert client.get("/me").json()["google_status"] == "connected"
