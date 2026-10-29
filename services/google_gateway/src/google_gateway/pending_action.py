"""The pending action: the exact outgoing email, its hash, and when it expires (invariant 4).

The payload is everything execution will do, frozen at creation: recipients, subject,
body, slots. Its SHA-256 over a canonical JSON form is the content hash. An approval is
bound to this hash (step 1.9), and execution recomputes it (step 1.10): if a single
character changed, the approval no longer matches and nothing is sent (T3, T10).

A pending action expires at the end of the nearest workday that has not ended yet, so an
approval cannot be given days later for a slot that is long gone (E7).
"""

import hashlib
import json
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from google_gateway.email_template import OutgoingEmail
from shared.messages import AgentContext, ProposeSlots


def reply_payload(
    *,
    decision: ProposeSlots,
    email: OutgoingEmail,
    recipients: tuple[str, ...],
    gmail_thread_id: str,
    time_zone: str,
) -> dict[str, Any]:
    return {
        "kind": "reply_with_slots",
        "gmail_thread_id": gmail_thread_id,
        "to": list(recipients),
        "subject": email.subject,
        "body": email.body,
        "language": decision.language,
        "duration_minutes": decision.duration_minutes,
        "slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()} for s in decision.slots],
        "time_zone": time_zone,
    }


def content_hash(payload: dict[str, Any]) -> str:
    # Canonical form: sorted keys, no whitespace, UTF-8. The same content always hashes
    # the same; any change, even one character, gives another hash.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def expires_at(context: AgentContext, end_of_workday: time) -> datetime:
    """End of the nearest workday (settings, 0 = Sunday) that has not ended yet."""
    tz = ZoneInfo(context.time_zone)
    now = context.now.astimezone(tz)
    for offset in range(8):
        day = now.date() + timedelta(days=offset)
        if (day.weekday() + 1) % 7 not in context.work_days:
            continue
        end = datetime.combine(day, end_of_workday, tz)
        if end > now:
            return end
    raise ValueError("no work days configured")
