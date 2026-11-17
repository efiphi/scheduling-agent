"""The outgoing email (email_template.py): code-built, disclosure always there (invariant 10)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from google_gateway.email_template import DISCLOSURE, build_reply, reply_subject
from shared.messages import Interval

TZ = ZoneInfo("Asia/Jerusalem")
SLOTS = (
    Interval(
        start=datetime(2026, 11, 3, 10, tzinfo=TZ), end=datetime(2026, 11, 3, 10, 30, tzinfo=TZ)
    ),
    Interval(
        start=datetime(2026, 11, 4, 14, tzinfo=TZ), end=datetime(2026, 11, 4, 14, 30, tzinfo=TZ)
    ),
)


def reply(language: str, opening: str = "Thanks!") -> tuple[str, str]:
    email = build_reply(
        language=language,
        opening_line=opening,
        slots=SLOTS,
        duration_minutes=30,
        time_zone="Asia/Jerusalem",
        incoming_subject="Quick call?",
    )
    return email.subject, email.body


@pytest.mark.parametrize("language", ["he", "en"])
def test_invariant_10_disclosure_is_always_the_last_line(language: str) -> None:
    _, body = reply(language)
    assert body.splitlines()[-1] == DISCLOSURE[language]


def test_hebrew_slots_name_the_day_and_the_time_zone() -> None:
    _, body = reply("he", "תודה על הפנייה!")
    assert "יום שלישי, 3 בנובמבר, 10:00-10:30" in body
    # No time zone named (owner's decision, 31.10): times are in the user's own zone.
    assert "שעון" not in body
    assert body.startswith("תודה על הפנייה!")


def test_english_slots_are_written_out_in_the_users_zone() -> None:
    _, body = reply("en")
    assert "Tuesday, 3 November, 10:00-10:30" in body
    assert "time)" not in body


def test_slot_times_are_written_in_the_users_zone_even_if_given_in_utc() -> None:
    utc = (
        Interval(
            start=SLOTS[0].start.astimezone(ZoneInfo("UTC")),
            end=SLOTS[0].end.astimezone(ZoneInfo("UTC")),
        ),
    )
    email = build_reply(
        language="en",
        opening_line="Hi",
        slots=utc,
        duration_minutes=30,
        time_zone="Asia/Jerusalem",
        incoming_subject="x",
    )
    assert "10:00-10:30" in email.body


@pytest.mark.parametrize(
    ("incoming", "expected"),
    [
        ("Quick call?", "Re: Quick call?"),
        ("Re: Quick call?", "Re: Quick call?"),
        ("", "Re:"),
        ("Hi\r\nBcc: attacker@example.org", "Re: Hi Bcc: attacker@example.org"),
    ],
)
def test_t1_subject_reuses_the_incoming_one_without_line_breaks(
    incoming: str, expected: str
) -> None:
    # A line break inside a header would let the sender inject another header (Bcc).
    assert reply_subject(incoming) == expected


def test_subject_is_shortened() -> None:
    assert len(reply_subject("x" * 500)) == 150
