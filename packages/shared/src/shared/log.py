"""Logging for every process: one JSON object per line, on stdout (Layer 3, T22).

    from shared import log
    log.configure("google-gateway")

Why JSON: Loki and Grafana can filter on fields (level, service, trace_id) instead of
parsing text, and a log line can link to its trace. It also closes log injection: an
email subject with a line break in it cannot forge a second log line, because json.dumps
escapes the newline.

What goes in a line is the caller's job (outcomes and ids, never content). Redaction here is
a second line of defense: if a token ever reaches a message by mistake, its known shapes are
masked before the line is written.

LOG_FORMAT=text gives the old human-readable format, for running a process in a terminal.
"""

import json
import logging
import os
import re
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

# HTTP clients log request URLs and headers at INFO and below. Kept at WARNING everywhere.
QUIET_LOGGERS = ("httpx", "httpx2", "anthropic", "googleapiclient", "urllib3")

# Known secret shapes (T22). Matched values become "[redacted]".
_REDACTIONS = [
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]+"),  # Google access token
    re.compile(r"\b1//[A-Za-z0-9._-]{20,}"),  # Google refresh token
    re.compile(r"\bEAA[A-Za-z0-9]{20,}"),  # Meta access token
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"),  # Anthropic API key
    re.compile(
        r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|code|state)=[^\s&]+"
    ),
]

# Attributes every LogRecord has; anything else came from `extra=` and is logged as a field.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


def redact(text: str) -> str:
    for pattern in _REDACTIONS:
        text = pattern.sub("[redacted]", text)
    return text


def _trace_ids() -> dict[str, str]:
    """The current OpenTelemetry trace and span, when there is one (step 3.3)."""
    try:
        from opentelemetry import trace
    except ImportError:
        return {}
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {}
    return {"trace_id": f"{context.trace_id:032x}", "span_id": f"{context.span_id:016x}"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        line.update(_trace_ids())
        for key, value in vars(record).items():
            if key not in _STANDARD and key not in line:
                line[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            line["error"] = redact("".join(traceback.format_exception(*record.exc_info)))
        return json.dumps(line, ensure_ascii=False, default=str)


class _RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure(service: str, level: int = logging.INFO) -> None:
    """Send every logger, uvicorn's included, through one stdout handler."""
    handler = logging.StreamHandler(sys.stdout)
    if os.environ.get("LOG_FORMAT", "json") == "text":
        handler.setFormatter(
            _RedactingTextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn installs its own text handlers before it imports the app; route them here too.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # Never the access log: it prints every request URL, and the OAuth callback URLs carry
    # the authorization code and state (T16, T22). The services also start uvicorn with
    # --no-access-log; this keeps it off even if a process is started without that flag.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
