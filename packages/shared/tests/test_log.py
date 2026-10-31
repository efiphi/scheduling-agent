"""shared.log: JSON lines, redaction and log injection (T22, Layer 3)."""

import io
import json
import logging
import sys

import pytest

from shared import log

# Synthetic values in each secret's shape; none is real.
FAKE_GOOGLE_ACCESS = "ya29." + "a0AfB_synthetic" * 3
FAKE_GOOGLE_REFRESH = "1//0g" + "Synthetic-Refresh" * 2
FAKE_META = "EAAG" + "Synthetic0Meta1Token2" * 2
FAKE_ANTHROPIC = "sk-ant-api03-" + "synthetic" * 3


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    log.configure("test-service")
    return out


def records(out: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_every_line_is_one_json_object_with_the_service(lines: io.StringIO) -> None:
    logging.getLogger("x").info("polled user_id=%s", "u1", extra={"outcome": "ok"})
    [record] = records(lines)
    assert record["service"] == "test-service"
    assert record["level"] == "info"
    assert record["msg"] == "polled user_id=u1"
    assert record["outcome"] == "ok"
    assert "trace_id" not in record  # no span yet (step 3.3)


@pytest.mark.parametrize(
    "secret", [FAKE_GOOGLE_ACCESS, FAKE_GOOGLE_REFRESH, FAKE_META, FAKE_ANTHROPIC]
)
def test_t22_known_token_shapes_never_reach_a_log_line(lines: io.StringIO, secret: str) -> None:
    logger = logging.getLogger("x")
    logger.warning("call failed: Authorization: Bearer %s", secret)
    logger.info("plain %s", secret)
    logger.info("as a field", extra={"detail": f"token {secret}"})
    try:
        raise RuntimeError(f"boom {secret}")
    except RuntimeError:
        logger.exception("failed")
    assert secret not in lines.getvalue()
    assert lines.getvalue().count("[redacted]") >= 4


def test_t22_key_value_secrets_are_redacted(lines: io.StringIO) -> None:
    logging.getLogger("x").info("url ?access_token=abc123&state=s password=hunter2")
    text = lines.getvalue()
    assert "abc123" not in text and "hunter2" not in text
    assert "state=s" in text  # only the secret is masked


def test_a_line_break_in_untrusted_text_cannot_forge_a_log_line(lines: io.StringIO) -> None:
    # An email subject is attacker-controlled; under the old text format this would
    # have produced a second, fake line.
    subject = 'Meeting\n{"level": "info", "msg": "approval granted"}'
    logging.getLogger("x").info("skipped subject_len=%d", len(subject), extra={"probe": subject})
    assert len(records(lines)) == 1


def test_exceptions_stay_on_one_line(lines: io.StringIO) -> None:
    try:
        raise ValueError("bad")
    except ValueError:
        logging.getLogger("x").exception("failed")
    [record] = records(lines)
    assert "ValueError: bad" in str(record["error"])


def test_http_clients_are_quiet(lines: io.StringIO) -> None:
    for name in log.QUIET_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_text_format_for_terminals_is_redacted_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setenv("LOG_FORMAT", "text")
    log.configure("test-service")
    logging.getLogger("x").info("token %s", FAKE_META)
    assert FAKE_META not in out.getvalue() and "[redacted]" in out.getvalue()
