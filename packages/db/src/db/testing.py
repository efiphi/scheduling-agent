"""Pytest fixtures for tests that run against a real Postgres (loaded by the root conftest.py).

Connection details come from the environment (the same variables as deploy/compose/.env).
Without them these tests are skipped locally; CI sets REQUIRE_DB=1 so a missing database
fails the run instead of silently skipping it.
"""

import os

import pytest
from sqlalchemy import Engine

from db.engine import make_engine

_PASSWORDS = {
    "scheduling_owner": "OWNER_DB_PASSWORD",
    "api_service": "API_DB_PASSWORD",
    "gateway_service": "GATEWAY_DB_PASSWORD",
}


def _engine(role: str) -> Engine:
    password = os.environ.get(_PASSWORDS[role])
    if not password:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(f"{_PASSWORDS[role]} is not set but REQUIRE_DB=1")
        pytest.skip("database tests need the role passwords in the environment")
    host = os.environ.get("DB_HOST", "127.0.0.1")
    port = int(os.environ.get("DB_PORT", "5432"))
    return make_engine(role, password, host, port)


@pytest.fixture(scope="session")
def owner() -> Engine:
    return _engine("scheduling_owner")


@pytest.fixture(scope="session")
def api() -> Engine:
    return _engine("api_service")


@pytest.fixture(scope="session")
def gateway() -> Engine:
    return _engine("gateway_service")
