"""The outgoing email, built by code from a fixed template (ADR-012, invariant 10).

Only the opening line comes from the model, already checked by the policy guard. The
slots are written by code with the time zone spelled out (E3), and the disclosure line is
appended by code on every email, so a manipulated model can neither drop it nor add
content. The subject reuses the incoming one: untrusted, so line breaks are removed (a
line break in a header could inject another header, such as Bcc) and it is shortened.
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from shared.messages import Interval

MAX_SUBJECT = 150

DISCLOSURE = {
    "he": "המייל הזה נשלח על ידי עוזר התיאום האוטומטי שלי, אחרי שאישרתי אותו.",
    "en": "This email was sent by my automated scheduling assistant, after I approved it.",
}
INTRO = {
    "he": "אפשר לבחור את אחד המועדים ({duration} דקות, לפי {zone}):",
    "en": "Any of these times works ({duration} minutes, {zone} time):",
}
CLOSING = {
    "he": "אם אף אחד מהם לא מתאים, אשמח שתציע מועד אחר.",
    "en": "If none of these work, feel free to suggest another time.",
}
ZONE_NAMES = {
    "he": {"Asia/Jerusalem": "שעון ישראל"},
    "en": {"Asia/Jerusalem": "Israel"},
}
HEBREW_DAYS = ("שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון")
HEBREW_MONTHS = (
    "בינואר", "בפברואר", "במרץ", "באפריל", "במאי", "ביוני",
    "ביולי", "באוגוסט", "בספטמבר", "באוקטובר", "בנובמבר", "בדצמבר",
)  # fmt: skip


@dataclass(frozen=True)
class OutgoingEmail:
    subject: str
    body: str


def reply_subject(incoming: str) -> str:
    subject = " ".join(incoming.split())  # no CR/LF: header injection (T1)
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}" if subject else "Re:"
    return subject[:MAX_SUBJECT]


def format_slot(slot: Interval, language: str, tz: ZoneInfo) -> str:
    start, end = slot.start.astimezone(tz), slot.end.astimezone(tz)
    if language == "he":
        day = f"יום {HEBREW_DAYS[start.weekday()]}, {start.day} {HEBREW_MONTHS[start.month - 1]}"
    else:
        day = f"{start:%A}, {start.day} {start:%B}"
    return f"{day}, {_clock(start)}-{_clock(end)}"


def build_reply(
    *,
    language: str,
    opening_line: str,
    slots: tuple[Interval, ...],
    duration_minutes: int,
    time_zone: str,
    incoming_subject: str,
) -> OutgoingEmail:
    tz = ZoneInfo(time_zone)
    zone = ZONE_NAMES[language].get(time_zone, time_zone)
    lines = [
        opening_line,
        "",
        INTRO[language].format(duration=duration_minutes, zone=zone),
        *(f"- {format_slot(slot, language, tz)}" for slot in slots),
        "",
        CLOSING[language],
        "",
        "--",
        DISCLOSURE[language],
    ]
    return OutgoingEmail(subject=reply_subject(incoming_subject), body="\n".join(lines))


def _clock(moment: datetime) -> str:
    return f"{moment:%H:%M}"
