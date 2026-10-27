"""Reading Gmail for one user (ADR-003). Read-only: this module never sends or modifies.

Two reads per message, on purpose:
1. `message_metadata` - headers and labels. Enough for most of the rule filter
   (mail_filter.py): newsletters, auto-replies and the user's own mail are decided here,
   and their bodies are never fetched.
2. `message_body` - the full text, only when the filter has to look for a request in it.
"""

import base64
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_gateway.mail_body import text_from_payload

# Headers the filter reads. Gmail returns them already decoded.
FILTER_HEADERS = (
    "From",
    "To",
    "Cc",
    "Subject",
    "Auto-Submitted",
    "X-Autoreply",
    "X-Autorespond",
    "Precedence",
    "List-Id",
    "List-Unsubscribe",
)


class HistoryExpired(Exception):
    """The stored historyId is too old for Gmail (after long downtime): resync needed."""


@dataclass(frozen=True)
class MessageRef:
    message_id: str
    thread_id: str


@dataclass(frozen=True)
class MessageMeta:
    message_id: str
    thread_id: str
    labels: frozenset[str]
    # Lower-case header name -> value. Untrusted: written by whoever sent the email.
    headers: dict[str, str]
    snippet: str
    received_at: datetime

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


class GmailReader(Protocol):
    def current_history_id(self) -> str: ...

    def added_since(self, history_id: str) -> tuple[list[MessageRef], str]:
        """Inbox messages added after `history_id`, and the history id to store next."""
        ...

    def recent(self, days: int) -> list[MessageRef]: ...

    def message_metadata(self, message_id: str) -> MessageMeta: ...

    def message_body(self, message_id: str) -> str: ...


class GoogleGmailReader:
    def __init__(self, credentials: Any) -> None:
        self._users = build("gmail", "v1", credentials=credentials, cache_discovery=False).users()

    def current_history_id(self) -> str:
        return str(self._users.getProfile(userId="me").execute()["historyId"])

    def added_since(self, history_id: str) -> tuple[list[MessageRef], str]:
        refs: list[MessageRef] = []
        latest = history_id
        try:
            for page in self._pages(
                self._users.history().list,
                userId="me",
                startHistoryId=history_id,
                historyTypes=["messageAdded"],
                labelId="INBOX",
            ):
                latest = str(page.get("historyId", latest))
                for record in page.get("history", []):
                    for added in record.get("messagesAdded", []):
                        message = added["message"]
                        refs.append(MessageRef(message["id"], message["threadId"]))
        except HttpError as error:
            if error.resp.status == 404:
                raise HistoryExpired from error
            raise
        return refs, latest

    def recent(self, days: int) -> list[MessageRef]:
        refs: list[MessageRef] = []
        for page in self._pages(
            self._users.messages().list, userId="me", q=f"in:inbox newer_than:{days}d"
        ):
            refs.extend(MessageRef(m["id"], m["threadId"]) for m in page.get("messages", []))
        return refs

    def message_metadata(self, message_id: str) -> MessageMeta:
        message = (
            self._users.messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=list(FILTER_HEADERS),
            )
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
        return MessageMeta(
            message_id=message["id"],
            thread_id=message["threadId"],
            labels=frozenset(message.get("labelIds", [])),
            headers=headers,
            snippet=message.get("snippet", ""),
            received_at=datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=UTC),
        )

    def message_body(self, message_id: str) -> str:
        message = self._users.messages().get(userId="me", id=message_id, format="full").execute()
        return text_from_payload(message["payload"], _decode)

    @staticmethod
    def _pages(method: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        token: str | None = None
        while True:
            page: dict[str, Any] = method(pageToken=token, **kwargs).execute()
            yield page
            token = page.get("nextPageToken")
            if not token:
                return


def _decode(data: str) -> bytes:
    # Gmail uses base64url, sometimes without padding.
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
