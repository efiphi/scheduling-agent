"""Polling each connected mailbox for new email (ADR-003, UC-M1, UC-M8).

For one user, under a per-user lock:
1. Read what was added to the inbox since the stored history id.
2. For each new message: the rule filter (mail_filter.py), which opens the body only
   when headers alone cannot decide. The body is fetched at most once per message.
   - passed, and under the rate limit: record the thread, queue an EmailTask for the
     agent. The email is untrusted data (invariant 2).
   - skipped: keep sender, subject and time for the daily summary (E9); the body, if it
     was read, is dropped.
3. Store the new history id, only after every message was handled. A crash before that
   repeats the batch next time, and the "handled" markers make the repeat harmless (E8).

Nothing from an email's content is logged: counts and ids only (T22).
"""

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.utils import getaddresses
from uuid import UUID, uuid4

from google.auth.exceptions import RefreshError
from pydantic import ValidationError

from google_gateway.coordination import PollCoordination
from google_gateway.gmail import GmailReader, HistoryExpired, MessageMeta, MessageRef
from google_gateway.mail_filter import Decision, classify, sender_address
from google_gateway.mail_store import MailStore
from google_gateway.token_crypto import EncryptedToken
from shared import tracing
from shared.messages import (
    MAX_BODY_CHARS,
    MAX_SUBJECT_CHARS,
    EmailTask,
    UntrustedEmail,
    UntrustedText,
)

logger = logging.getLogger(__name__)
_tracer = tracing.tracer(__name__)

# After an expired history id, look back this far. Anything older is not "new" anymore.
RESYNC_DAYS = 1
MAX_PARTICIPANTS = 50

OpenGmail = Callable[[UUID, EncryptedToken], GmailReader]


@dataclass(frozen=True)
class MailboxPoller:
    store: MailStore
    coordination: PollCoordination
    open_gmail: OpenGmail
    clock: Callable[[], datetime]

    def poll_all(self) -> None:
        for user_id in self.store.users_to_poll():
            try:
                self.poll_user(user_id)
            except Exception as exc:
                # One broken mailbox must not stop the others. Type only: messages from
                # Google's libraries can include request details.
                logger.error("poll failed: user_id=%s error=%s", user_id, type(exc).__name__)

    def poll_user(self, user_id: UUID) -> Counter[str]:
        outcomes: Counter[str] = Counter()
        with self.coordination.lock_user(user_id) as locked:
            if not locked:
                outcomes["locked"] += 1
                return outcomes
            mailbox = self.store.mailbox(user_id)
            if mailbox is None:
                return outcomes
            gmail = self.open_gmail(user_id, mailbox.token)
            try:
                self._poll(user_id, mailbox.email, mailbox.history_id, gmail, outcomes)
            except RefreshError:
                # Revoked by the user, or the 7-day limit of testing mode (E13). Stop polling
                # until they reconnect; the alert to the user comes with steps 1.9 and 1b.
                self.store.mark_expired(user_id)
                outcomes["token_rejected"] += 1
        logger.info("polled user_id=%s %s", user_id, dict(sorted(outcomes.items())))
        return outcomes

    def _poll(
        self,
        user_id: UUID,
        user_email: str,
        history_id: str | None,
        gmail: GmailReader,
        outcomes: Counter[str],
    ) -> None:
        if history_id is None:
            # First poll after connecting: start from now, do not process the old inbox.
            self.store.set_history_id(user_id, gmail.current_history_id())
            self.store.audit(user_id, "gmail_sync_started", {})
            return
        try:
            refs, next_history_id = gmail.added_since(history_id)
        except HistoryExpired:
            # Take the new starting point first, so mail arriving meanwhile is not lost.
            next_history_id = gmail.current_history_id()
            refs = gmail.recent(RESYNC_DAYS)
            self.store.audit(user_id, "gmail_history_reset", {"messages": len(refs)})
        for ref in _unique(refs):
            outcomes[self._handle(user_id, user_email, ref, gmail)] += 1
        self.store.set_history_id(user_id, next_history_id)

    def _handle(self, user_id: UUID, user_email: str, ref: MessageRef, gmail: GmailReader) -> str:
        if self.coordination.already_handled(user_id, ref.message_id):
            return "duplicate"
        # Each new email starts its own trace; every later hop continues it (shared.tracing).
        with _tracer.start_as_current_span(
            "email.received", context=tracing.new_trace(), attributes={"user.id": str(user_id)}
        ) as span:
            outcome = self._handle_new(user_id, user_email, ref, gmail)
            span.set_attribute("email.outcome", outcome)
            return outcome

    def _handle_new(
        self, user_id: UUID, user_email: str, ref: MessageRef, gmail: GmailReader
    ) -> str:
        meta = gmail.message_metadata(ref.message_id)
        tracked = self.store.is_tracked_thread(user_id, meta.thread_id)
        body = _Body(gmail, ref.message_id)
        decision = classify(meta, user_email=user_email, tracked_thread=tracked, read_body=body)
        outcome = self._act(user_id, user_email, meta, decision, body)
        self.coordination.mark_handled(user_id, ref.message_id)
        return outcome

    def _act(
        self,
        user_id: UUID,
        user_email: str,
        meta: MessageMeta,
        decision: Decision,
        body: "_Body",
    ) -> str:
        sender = sender_address(meta)
        if decision.passes and not self.coordination.take_rate_slot(user_id, sender):
            self.store.security_event(user_id, "email_rate_limited", {})
            self._record_skipped(user_id, meta)
            return "rate_limited"
        if not decision.passes:
            if decision.recorded_as_skipped:
                self._record_skipped(user_id, meta)
            return decision.reason.value

        try:
            email = UntrustedEmail(
                gmail_message_id=meta.message_id,
                sender=sender,
                subject=UntrustedText(meta.header("Subject")[:MAX_SUBJECT_CHARS]),
                # The whole body, quotes included: they are the thread's context so far.
                body_text=UntrustedText(body()[:MAX_BODY_CHARS]),
                received_at=meta.received_at,
            )
        except ValidationError:
            # e.g. a From header with no usable address. Keep it visible, don't guess.
            self._record_skipped(user_id, meta)
            return "invalid_message"
        thread_id = self.store.upsert_thread(
            user_id, meta.thread_id, _participants(meta, user_email)
        )
        context = self.store.agent_context(user_id, self.clock())
        offered = self.store.offered_slots(user_id, meta.thread_id)
        if offered:
            # A reply to our proposal: the agent may pick one of these by number (UC-M2).
            context = context.model_copy(update={"proposed_slots": offered})
        self.coordination.enqueue(
            EmailTask(
                task_id=uuid4(),
                user_id=user_id,
                thread_id=thread_id,
                email=email,
                context=context,
            )
        )
        return decision.reason.value

    def _record_skipped(self, user_id: UUID, meta: MessageMeta) -> None:
        sender = sender_address(meta) or meta.header("From")
        self.store.record_skipped(user_id, sender, meta.header("Subject"), meta.received_at)


class _Body:
    """Fetches a message body on first use and remembers it."""

    def __init__(self, gmail: GmailReader, message_id: str) -> None:
        self._gmail = gmail
        self._message_id = message_id
        self._text: str | None = None

    def __call__(self) -> str:
        if self._text is None:
            self._text = self._gmail.message_body(self._message_id)
        return self._text


def _unique(refs: list[MessageRef]) -> list[MessageRef]:
    return list(dict.fromkeys(refs))


def _participants(meta: MessageMeta, user_email: str) -> list[str]:
    """Everyone on the message except the user: the only people a reply may go to (T5)."""
    headers = [meta.header(name) for name in ("From", "To", "Cc")]
    addresses = {address.lower() for _, address in getaddresses(headers) if "@" in address}
    addresses.discard(user_email.lower())
    return sorted(addresses)[:MAX_PARTICIPANTS]
