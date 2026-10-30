from typing import cast

from api_fakes import FakeLogin, FakeRedis, FakeSessions, FakeStore
from fastapi.testclient import TestClient
from redis import Redis

from api.main import Deps, create_app


def client() -> TestClient:
    deps = Deps(
        login=FakeLogin(),
        sessions=FakeSessions(),
        store=FakeStore(),
        redis=cast(Redis, FakeRedis()),
        web_app_url="http://localhost:5173/",
        cookie_secure=True,
    )
    return TestClient(create_app(deps))


def test_healthz_returns_ok() -> None:
    response = client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_response_carries_security_headers() -> None:
    response = client().get("/healthz")
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert "server" not in response.headers or "uvicorn" not in response.headers["server"]
