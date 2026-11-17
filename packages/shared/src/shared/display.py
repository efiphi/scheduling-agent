"""Text from an email, made safe to show the user (ADR-019, T31).

The sender's subject, the model's summary of the email and the model's question to the user
are shown, never acted on. All are written under an attacker's influence, so:
- Invisible and direction-changing characters are removed: they can make text read
  differently from what it says.
- Text with a link, an address or a long number is dropped whole: it must not become a way
  to place a phishing link in front of the user. Too long is dropped too. It is never cut,
  since half a sentence can change what it says.
"""

import re

MAX_SUMMARY_CHARS = 1500
MAX_QUESTION_CHARS = 300

_INVISIBLE = re.compile("[­​-‏‪-‮⁠-⁩﻿]")
_FORBIDDEN = re.compile(
    r"@|https?://|www\.|(?<![a-z0-9-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?![a-z0-9-])|\d{6,}",
    re.I,
)


def clean_line(text: str) -> str:
    """One line with no invisible characters; every run of whitespace becomes one space."""
    return " ".join(_INVISIBLE.sub("", text).split())


def _safe(text: str | None, limit: int) -> str | None:
    line = clean_line(text or "")
    if not line or len(line) > limit or _FORBIDDEN.search(line):
        return None
    return line


def safe_summary(text: str | None) -> str | None:
    """The summary as it may be shown, or None if it may not be shown at all."""
    return _safe(text, MAX_SUMMARY_CHARS)


def safe_question(text: str | None) -> str | None:
    """The model's question to the user as it may be shown, or None (UC-M7, T31)."""
    return _safe(text, MAX_QUESTION_CHARS)
