"""The outgoing message itself (gmail_sender.py): direction, escaping, headers."""

import email
from email.policy import default
from uuid import uuid4

import pytest

from google_gateway.gmail_sender import build_message, message_id, rtl_html

BODY = (
    "תודה על הפנייה!\n\nאפשר לבחור את אחד המועדים (30 דקות):\n- יום שלישי, 3 בנובמבר, 12:00-12:30"
)


def parts(raw: bytes) -> dict[str, str]:
    message = email.message_from_bytes(raw, policy=default)
    return {p.get_content_type(): p.get_content() for p in message.walk() if not p.is_multipart()}


def test_a_hebrew_email_reads_right_to_left() -> None:
    raw = build_message(
        to=["dana@example.org"],
        subject="Re: פגישה",
        body=BODY,
        idempotency_key=uuid4(),
        in_reply_to=None,
        language="he",
    )
    found = parts(raw)
    # Email lines end in CRLF (the SMTP policy); the text is otherwise the approved one.
    assert found["text/plain"].replace("\r\n", "\n").strip() == BODY.strip()
    assert 'dir="rtl"' in found["text/html"]
    assert "יום שלישי, 3 בנובמבר, 12:00-12:30" in found["text/html"]


def test_an_english_email_stays_plain_text() -> None:
    raw = build_message(
        to=["dana@example.org"],
        subject="Re: Call",
        body="Hi",
        idempotency_key=uuid4(),
        in_reply_to=None,
        language="en",
    )
    assert list(parts(raw)) == ["text/plain"]


def test_t1_the_html_carries_no_markup_from_the_text() -> None:
    html = rtl_html('שלום <script>alert(1)</script> <a href="https://evil.example">x</a>')
    assert "<script>" not in html and "<a href" not in html
    assert "&lt;script&gt;" in html


def test_the_html_adds_nothing_but_line_breaks() -> None:
    html = rtl_html("שורה אחת\nשורה שתיים")
    inner = html.split('">', 1)[1].rsplit("</div>", 1)[0]
    assert inner == "שורה אחת<br>שורה שתיים"


@pytest.mark.parametrize("language", ["he", "en"])
def test_headers_are_set_by_code(language: str) -> None:
    key = uuid4()
    raw = build_message(
        to=["dana@example.org"],
        subject="Re: x",
        body="b",
        idempotency_key=key,
        in_reply_to="<orig@example.org>",
        language=language,
    )
    message = email.message_from_bytes(raw, policy=default)
    assert message["Message-ID"] == message_id(key)
    assert message["In-Reply-To"] == "<orig@example.org>"
