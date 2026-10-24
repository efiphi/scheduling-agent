from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_healthz_returns_ok() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_reveals_nothing_about_the_deployment() -> None:
    # Exactly one field: no version, host or dependency status for an anonymous caller.
    assert set(client.get("/healthz").json()) == {"status"}


def test_unknown_path_is_404() -> None:
    assert client.get("/no-such-endpoint").status_code == 404


def test_healthz_accepts_get_only() -> None:
    assert client.post("/healthz").status_code == 405
