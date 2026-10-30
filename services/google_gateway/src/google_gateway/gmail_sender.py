"""Sending the approved reply through Gmail (gmail.send scope only, ADR-010).

The message is built with the standard library's email package, whose default policy
refuses a header value containing a line break, a second guard against header injection
after email_template.py removed them (T1).

Idempotency (E8): the Message-ID is derived from the action's idempotency key. Before
sending, the executor asks Gmail whether a message with that Message-ID already exists. So
a retry after a crash between "sent" and "recorded as sent" never sends twice.
"""

import base64
from email.message import EmailMessage
from email.policy import SMTP
from typing import Any, Protocol
from uuid import UUID

from googleapiclient.discovery import build

MESSAGE_ID_DOMAIN = "scheduling-agent.invalid"  # RFC 2606: a domain that never resolves


def message_id(idempotency_key: UUID) -> str:
    return f"<{idempotency_key}@{MESSAGE_ID_DOMAIN}>"


def build_message(
    *, to: list[str], subject: str, body: str, idempotency_key: UUID, in_reply_to: str | None
) -> bytes:
    message = EmailMessage(policy=SMTP)
    message["To"] = ", ".join(to)  # From is set by Gmail: the authenticated mailbox
    message["Subject"] = subject
    message["Message-ID"] = message_id(idempotency_key)
    if in_reply_to:
        # Threads the reply in the recipient's mail client, not only in Gmail.
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to
    message.set_content(body)
    return message.as_bytes()


class MailSender(Protocol):
    def latest_message_id(self, gmail_thread_id: str) -> str | None: ...

    def already_sent(self, idempotency_key: UUID) -> str | None:
        """The Gmail id of a message already sent for this key, if any."""
        ...

    def send(self, raw: bytes, gmail_thread_id: str) -> str: ...


class GoogleMailSender:
    def __init__(self, credentials: Any) -> None:
        self._users = build("gmail", "v1", credentials=credentials, cache_discovery=False).users()

    def latest_message_id(self, gmail_thread_id: str) -> str | None:
        thread = (
            self._users.threads()
            .get(userId="me", id=gmail_thread_id, format="metadata", metadataHeaders=["Message-ID"])
            .execute()
        )
        messages = thread.get("messages", [])
        if not messages:
            return None
        headers = messages[-1].get("payload", {}).get("headers", [])
        return next((h["value"] for h in headers if h["name"].lower() == "message-id"), None)

    def already_sent(self, idempotency_key: UUID) -> str | None:
        found = (
            self._users.messages()
            .list(
                userId="me", q=f"rfc822msgid:{message_id(idempotency_key)}", includeSpamTrash=True
            )
            .execute()
        )
        messages = found.get("messages", [])
        return str(messages[0]["id"]) if messages else None

    def send(self, raw: bytes, gmail_thread_id: str) -> str:
        sent = (
            self._users.messages()
            .send(
                userId="me",
                body={"raw": base64.urlsafe_b64encode(raw).decode(), "threadId": gmail_thread_id},
            )
            .execute()
        )
        return str(sent["id"])
