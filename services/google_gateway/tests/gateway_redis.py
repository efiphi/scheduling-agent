"""A real Redis for the `redis`-marked tests, on a database index of its own (15).
Loaded as a pytest plugin by the root conftest.py.

Skipped without REDIS_PASSWORD locally; with REQUIRE_DB=1 (CI) a missing Redis fails.
"""

import os
from collections.abc import Iterator

import pytest
from redis import Redis

TEST_DB = 15


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    password = os.environ.get("REDIS_PASSWORD")
    if not password:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail("REDIS_PASSWORD is not set but REQUIRE_DB=1")
        pytest.skip("Redis tests need REDIS_PASSWORD in the environment")
    client = Redis(
        host=os.environ.get("REDIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=password,
        db=TEST_DB,
    )
    client.flushdb()
    yield client
    client.flushdb()
