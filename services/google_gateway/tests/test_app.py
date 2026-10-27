"""The callback and result endpoints (app.py)."""

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from gateway_fakes import CODE, USER_EMAIL, FakeGoogle, FakeRepo, FakeStates

from google_gateway.app import CALLBACK_PATH, RESULT_PATH, create_app
from google_gateway.connection import ConnectFlow
from google_gateway.token_crypto import KEY_BYTES, TokenCipher


@pytest.fixture
def flow() -> ConnectFlow:
    user_id = uuid4()
    return ConnectFlow(
        states=FakeStates(),
        google=FakeGoogle(),
        repo=FakeRepo(emails={user_id: USER_EMAIL}),
        cipher=TokenCipher({1: bytes([7]) * KEY_BYTES}),
    )


def start(flow: ConnectFlow) -> str:
    user_id = next(iter(flow.repo.emails))  # type: ignore[attr-defined]
    return parse_qs(urlparse(flow.start(user_id)).query)["state"][0]


def test_callback_redirects_and_drops_the_code_from_the_url(flow: ConnectFlow) -> None:
    client = TestClient(create_app(flow))
    state = start(flow)
    response = client.get(
        CALLBACK_PATH, params={"state": state, "code": CODE}, follow_redirects=False
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location == f"{RESULT_PATH}?outcome=connected"
    assert CODE not in location and state not in location
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_result_page_is_hebrew_and_locked_down(flow: ConnectFlow) -> None:
    response = TestClient(create_app(flow)).get(RESULT_PATH, params={"outcome": "connected"})
    assert response.status_code == 200
    assert 'dir="rtl"' in response.text
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_forged_callback_ends_on_an_error_page(flow: ConnectFlow) -> None:
    client = TestClient(create_app(flow))
    response = client.get(CALLBACK_PATH, params={"state": "forged", "code": CODE})
    assert response.status_code == 400
    assert response.url.path == RESULT_PATH


def test_result_page_does_not_reflect_its_input(flow: ConnectFlow) -> None:
    client = TestClient(create_app(flow))
    response = client.get(RESULT_PATH, params={"outcome": "<script>alert(1)</script>"})
    assert response.status_code == 400
    assert "<script>" not in response.text and "alert" not in response.text


def test_no_api_docs_are_exposed(flow: ConnectFlow) -> None:
    client = TestClient(create_app(flow))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
