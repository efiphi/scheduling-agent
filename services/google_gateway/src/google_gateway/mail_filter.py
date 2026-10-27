"""The rule-based email filter (UC-M8, E9): which emails reach the agent and the LLM.

Runs on headers, labels and Gmail's snippet only (gmail.py), never the full body. Rules
are fixed and readable on purpose: cheap (T24), predictable, and easy to test. The cost
is that an unusually worded request can be missed (E9), which is why skipped emails are
recorded for the daily summary instead of vanishing.

Order matters:
1. Never process: not in the inbox (spam, drafts), or written by the user (T25).
2. Never answer machines: auto-replies, even inside a tracked thread (T25).
3. A thread the agent is already coordinating passes: "Tuesday works" has no keywords.
4. Bulk mail is skipped: mailing lists, newsletters, promotions, no-reply senders.
5. Calendar invitations and scheduling words pass; everything else is skipped.
"""

import re
from dataclasses import dataclass
from email.utils import parseaddr
from enum import StrEnum

from google_gateway.gmail import MessageMeta


class Reason(StrEnum):
    # Not recorded anywhere: not a request by definition.
    NOT_INBOX = "not_inbox"
    OWN_MESSAGE = "own_message"
    # Recorded in skipped_emails, so a missed request still shows up (E9).
    AUTO_REPLY = "auto_reply"
    BULK = "bulk"
    NO_REPLY_SENDER = "no_reply_sender"
    NO_MATCH = "no_match"
    # Passed to the agent.
    TRACKED_THREAD = "tracked_thread"
    INVITATION = "invitation"
    KEYWORD = "keyword"


PASSING = {Reason.TRACKED_THREAD, Reason.INVITATION, Reason.KEYWORD}
UNRECORDED = {Reason.NOT_INBOX, Reason.OWN_MESSAGE}

_NOT_INBOX_LABELS = {"SPAM", "TRASH", "DRAFT"}
_BULK_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}
_NO_REPLY = re.compile(r"(^|[._+-])(no-?reply|do-?not-?reply|mailer-daemon|postmaster)@", re.I)
_INVITATION = re.compile(r"^(updated )?invitation:|^הזמנה( מעודכנת)?:", re.I)
# English: whole words. Hebrew: stems, since prefixes attach to the word (לפגישה, בשיחה).
# Mind final letters: "זמין" ends in a final nun, "זמינה" and "זמינות" in a regular one.
_ENGLISH = re.compile(
    r"\b(meeting|meet|call|schedule|reschedule|available|availability|appointment|"
    r"catch up|sync|zoom)\b",
    re.I,
)
_HEBREW = re.compile(r"פגיש|להיפגש|נפגש|שיחה|שיחת|לקבוע|זמי[נן]|פנוי|זום")


@dataclass(frozen=True)
class Decision:
    reason: Reason

    @property
    def passes(self) -> bool:
        return self.reason in PASSING

    @property
    def recorded_as_skipped(self) -> bool:
        return not self.passes and self.reason not in UNRECORDED


def sender_address(meta: MessageMeta) -> str:
    return parseaddr(meta.header("From"))[1].lower()


def classify(meta: MessageMeta, *, user_email: str, tracked_thread: bool) -> Decision:
    if meta.labels & _NOT_INBOX_LABELS or "INBOX" not in meta.labels:
        return Decision(Reason.NOT_INBOX)
    sender = sender_address(meta)
    if sender == user_email.lower():
        return Decision(Reason.OWN_MESSAGE)
    if _is_auto_reply(meta):
        return Decision(Reason.AUTO_REPLY)
    if tracked_thread:
        return Decision(Reason.TRACKED_THREAD)
    if meta.labels & _BULK_LABELS or meta.header("List-Id") or meta.header("List-Unsubscribe"):
        return Decision(Reason.BULK)
    if meta.header("Precedence").lower() in {"bulk", "list", "junk"}:
        return Decision(Reason.BULK)
    if _NO_REPLY.search(sender):
        return Decision(Reason.NO_REPLY_SENDER)
    subject = meta.header("Subject")
    if _INVITATION.search(subject.strip()):
        return Decision(Reason.INVITATION)
    text = f"{subject}\n{meta.snippet}"
    if _ENGLISH.search(text) or _HEBREW.search(text):
        return Decision(Reason.KEYWORD)
    return Decision(Reason.NO_MATCH)


def _is_auto_reply(meta: MessageMeta) -> bool:
    # RFC 3834: anything but "no" means a machine sent it.
    auto_submitted = meta.header("Auto-Submitted").strip().lower()
    if auto_submitted and auto_submitted != "no":
        return True
    if meta.header("X-Autoreply") or meta.header("X-Autorespond"):
        return True
    return meta.header("Precedence").lower() == "auto_reply"
