"""Text from an email, made safe to show the user next to an approval (ADR-019, T31).

The sender's subject and the model's summary of the email are shown, never acted on. Both
are written under an attacker's influence, so:
- Invisible and direction-changing characters are removed: they can make text read
  differently from what it says.
- A summary with a link, an address or a long number is dropped whole: it must not become a
  way to place a phishing link in front of the user. Too long is dropped too. A summary is
  never cut, since half a sentence can change what it says; the user reads the original.
"""

import re

MAX_SUMMARY_CHARS = 1500

_INVISIBLE = re.compile("[­​-‏‪-‮⁠-⁩﻿]")
_FORBIDDEN_IN_SUMMARY = re.compile(
    r"@|https?://|www\.|(?<![a-z0-9-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?![a-z0-9-])|\d{6,}",
    re.I,
)


def clean_line(text: str) -> str:
    """One line with no invisible characters; every run of whitespace becomes one space."""
    return " ".join(_INVISIBLE.sub("", text).split())


def safe_summary(text: str | None) -> str | None:
    """The summary as it may be shown, or None if it may not be shown at all."""
    line = clean_line(text or "")
    if not line or len(line) > MAX_SUMMARY_CHARS or _FORBIDDEN_IN_SUMMARY.search(line):
        return None
    return line
