"""The deterministic policy guard (invariant 3, T3, T5, E1). Code, not a model.

Every plan from the agent is checked here before it can become a pending action, and
again at execution (step 1.10). The agent's own checks are not trusted: the agent reads
attacker-written email, so the gateway re-checks everything it relies on.

Checks for a reply with slots:
- Recipients: only people already in the thread, never the user, at least one and at
  most MAX_RECIPIENTS. The plan has no recipients field at all; they come from here (T5).
- Slots: 1 to 3, the requested length, in the future but within 31 days, on the user's
  work days and hours, not overlapping each other, and free right now (E1).
- Content: the opening line is the only free text: one line, at most 200 characters, no
  address, link or long number (T1, E5).
- Anomalies (fixed rules until request_patterns exist): too many replies already sent in
  this thread (an agent loop, T25), or too many actions for the user today (T24).
A violation rejects the plan; the reasons are recorded, the plan is not shown.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from zoneinfo import ZoneInfo

from shared.messages import MAX_FREE_BUSY_WINDOW, AgentContext, Interval, ProposeSlots

MAX_RECIPIENTS = 10
MAX_OPENING_LINE = 200
MAX_REPLIES_PER_THREAD = 3
MAX_ACTIONS_PER_DAY = 20
_FORBIDDEN = re.compile(r"@|https?://|www\.|\d{6,}", re.I)


@dataclass(frozen=True)
class GuardInput:
    decision: ProposeSlots
    context: AgentContext  # the user's settings, read by the gateway, not from the agent
    user_email: str
    participants: Sequence[str]
    busy_now: Sequence[Interval]
    replies_sent_in_thread: int
    actions_today: int


@dataclass(frozen=True)
class GuardResult:
    recipients: tuple[str, ...] = ()
    violations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allowed(self) -> bool:
        return not self.violations


def check_reply(g: GuardInput) -> GuardResult:
    violations: list[str] = []
    recipients = tuple(sorted({p.lower() for p in g.participants} - {g.user_email.lower()}))
    if not recipients:
        violations.append("no_recipients")
    if len(recipients) > MAX_RECIPIENTS:
        violations.append("too_many_recipients")

    violations += _check_slots(g)
    violations += _check_opening_line(g.decision.opening_line)

    if g.replies_sent_in_thread >= MAX_REPLIES_PER_THREAD:
        violations.append("thread_reply_limit")  # T25
    if g.actions_today >= MAX_ACTIONS_PER_DAY:
        violations.append("daily_action_limit")  # T24
    return GuardResult(recipients=recipients, violations=tuple(violations))


def _check_slots(g: GuardInput) -> list[str]:
    found: list[str] = []
    slots = g.decision.slots
    tz = ZoneInfo(g.context.time_zone)
    length = timedelta(minutes=g.decision.duration_minutes)
    now = g.context.now
    if not 1 <= len(slots) <= 3:
        found.append("slot_count")
    for slot in slots:
        start, end = slot.start.astimezone(tz), slot.end.astimezone(tz)
        if slot.end - slot.start != length:
            found.append("slot_length")
        if slot.start <= now or slot.start > now + MAX_FREE_BUSY_WINDOW:
            found.append("slot_out_of_range")
        if (start.weekday() + 1) % 7 not in g.context.work_days:  # settings: 0 = Sunday
            found.append("slot_not_a_work_day")
        if start.date() != end.date() or not (
            g.context.work_start <= start.time() and end.time() <= g.context.work_end
        ):
            found.append("slot_outside_work_hours")
        if any(_overlaps(slot, busy) for busy in g.busy_now):
            found.append("slot_not_free")  # E1: re-checked against the calendar now
    if any(_overlaps(a, b) for i, a in enumerate(slots) for b in slots[i + 1 :]):
        found.append("slots_overlap")
    return sorted(set(found))


def _check_opening_line(line: str) -> list[str]:
    if not line.strip() or len(line) > MAX_OPENING_LINE:
        return ["opening_line_length"]
    if "\n" in line or "\r" in line:
        return ["opening_line_multiline"]
    if _FORBIDDEN.search(line):
        return ["opening_line_content"]
    return []


def _overlaps(a: Interval, b: Interval) -> bool:
    return a.start < b.end and b.start < a.end
