"""Security events become a counter and a log line, with no personal data (ADR-022, T22)."""

import logging
from uuid import UUID

import pytest

from shared import security


def test_a_listed_kind_is_counted_and_logged_by_name(caplog: pytest.LogCaptureFixture) -> None:
    user = UUID("00000000-0000-0000-0000-000000000001")
    with caplog.at_level(logging.WARNING, logger="security"):
        security.record("stop_code_failed", user)
    assert caplog.messages == [f"security event: kind=stop_code_failed user_id={user}"]


def test_t22_an_unlisted_kind_cannot_add_a_series(caplog: pytest.LogCaptureFixture) -> None:
    # A typo, or a kind built from input, must not create a new metric series per value.
    with caplog.at_level(logging.WARNING, logger="security"):
        security.record("attacker@example.org")
    assert caplog.messages == ["security event: kind=unlisted user_id=-"]
