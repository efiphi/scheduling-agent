"""Writing a meeting slot for people, the same way in the email and on WhatsApp.

Times are shown in the user's own zone, without naming it: the user's correspondents are
expected to share it (the owner's decision, 31.10, see docs/02-threat-model.md E3).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

HEBREW_DAYS = ("שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון")
HEBREW_MONTHS = (
    "בינואר", "בפברואר", "במרץ", "באפריל", "במאי", "ביוני",
    "ביולי", "באוגוסט", "בספטמבר", "באוקטובר", "בנובמבר", "בדצמבר",
)  # fmt: skip


def format_slot(start: datetime, end: datetime, language: str, time_zone: str) -> str:
    """'יום שלישי, 3 בנובמבר, 10:00-10:30' or 'Tuesday, 3 November, 10:00-10:30'."""
    tz = ZoneInfo(time_zone)
    start, end = start.astimezone(tz), end.astimezone(tz)
    if language == "he":
        day = f"יום {HEBREW_DAYS[start.weekday()]}, {start.day} {HEBREW_MONTHS[start.month - 1]}"
    else:
        day = f"{start:%A}, {start.day} {start:%B}"
    return f"{day}, {start:%H:%M}-{end:%H:%M}"
