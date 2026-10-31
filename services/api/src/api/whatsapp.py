"""WhatsApp: the webhook's checks, the inbox rules, and sending (step 1b, ADR-014).

The api is the only holder of the Meta token (CLAUDE.md, invariant table).

Every webhook call, in this order:
1. Meta's signature (X-Hub-Signature-256: HMAC-SHA256 of the raw body with the App
   Secret), compared in constant time. Without it nothing is read: anyone can POST to a
   public URL, only Meta knows the secret.
Every message, in this order (invariant 12: the stop check comes before anything else):
2. Rate limit per sender number (T28): a flood is dropped before any work.
3. Who is it? The verified number of a user ("owner"), a backup number ("backup"), or
   unknown. An unknown number may only complete a pending verification code; anything
   else is dropped with no reply, only a security event (UC-W7, T8).
4. The stop code, checked against the argon2id hash of each user this number belongs to.
   A match pauses the agent and cancels every pending action. Failed attempts are rate
   limited and recorded (T28). A backup number can do nothing else.
5. Only then a normal message from the owner: it opens Meta's 24-hour window, in which
   the agent may write freely (approvals arrive here in step 1b-2).
Message text is untrusted: it is never logged, and only compared, never executed.
"""

import hashlib
import hmac
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx2
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import SecretStr
from redis import Redis

from api.store import ApiStore

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"
WINDOW_SECONDS = 24 * 3600
VERIFY_CODE_SECONDS = 10 * 60
SENDER_LIMIT = (20, 600)  # messages per sender per 10 minutes
STOP_FAILURE_LIMIT = (5, 3600)  # failed stop codes per sender per hour
VERIFY_FAILURE_LIMIT = (5, 600)  # unknown-number attempts per 10 minutes
# Unambiguous letters and digits (no 0/O, 1/I): 32**8 codes, about 10**12.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

PAUSED_REPLY = "הסוכן הושהה וכל הפעולות הממתינות בוטלו. חזרה לפעולה רק מהאפליקציה, אחרי התחברות."
VERIFIED_REPLY = "המספר אומת. מעכשיו אפשר לדבר איתי כאן."
OWNER_REPLY = "קיבלתי. פעולות שמחכות לאישור יגיעו לכאן עם כפתורים, וגם לאפליקציה."
AGENT_PAUSED_REPLY = "הסוכן מושהה. חזרה לפעולה מהאפליקציה."

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters


def hash_stop_code(code: str) -> str:
    return _hasher.hash(normalise(code))


def stop_code_matches(code_hash: str, text: str) -> bool:
    try:
        return _hasher.verify(code_hash, normalise(text))
    except (VerificationError, InvalidHashError):
        return False


def normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def valid_signature(app_secret: SecretStr, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def new_verification_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --- Sending ----------------------------------------------------------------------------


class WhatsAppSender(Protocol):
    def send_text(self, to: str, text: str) -> None: ...


class MetaSender:
    def __init__(self, token: SecretStr, phone_number_id: str) -> None:
        self._token = token
        self._url = f"{GRAPH}/{phone_number_id}/messages"

    def send_text(self, to: str, text: str) -> None:
        self._post({"to": to, "type": "text", "text": {"body": text}})

    def _post(self, message: dict[str, Any]) -> None:
        response = httpx2.post(
            self._url,
            json={"messaging_product": "whatsapp", **message},
            headers={"Authorization": f"Bearer {self._token.get_secret_value()}"},
            timeout=15,
        )
        if response.status_code >= 300:
            # Status only: the response body can echo the message (T22).
            logger.error("whatsapp send failed: status=%s", response.status_code)


def agent_display_number(token: SecretStr, phone_number_id: str) -> str:
    """The agent's number as people dial it, shown in the web app for verification."""
    try:
        response = httpx2.get(
            f"{GRAPH}/{phone_number_id}",
            params={"fields": "display_phone_number"},
            headers={"Authorization": f"Bearer {token.get_secret_value()}"},
            timeout=10,
        )
        return str(response.json().get("display_phone_number", ""))
    except (httpx2.HTTPError, ValueError):
        return ""


# --- State in Redis ---------------------------------------------------------------------


class InboxState:
    """Rate limits, the 24-hour window and pending verification codes, in Redis."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def over_limit(self, kind: str, key: str, limit: tuple[int, int]) -> bool:
        """Count one more event; True if this key is over `limit` (count, seconds)."""
        name = f"wa-rate:{kind}:{_digest(key)}"  # numbers stay out of key names
        pipe = self._redis.pipeline()
        pipe.incr(name)
        pipe.expire(name, limit[1], nx=True)
        count, _ = pipe.execute()
        return int(count) > limit[0]

    def limited(self, kind: str, key: str, limit: tuple[int, int]) -> bool:
        """True if this key already reached `limit`, without counting a new event."""
        count = self._redis.get(f"wa-rate:{kind}:{_digest(key)}")
        return count is not None and int(count) >= limit[0]

    def open_window(self, user_id: UUID) -> None:
        self._redis.set(f"wa-window:{user_id}", 1, ex=WINDOW_SECONDS)

    def window_open(self, user_id: UUID) -> bool:
        return bool(self._redis.exists(f"wa-window:{user_id}"))

    def start_verification(self, user_id: UUID) -> str:
        code = new_verification_code()
        self._redis.set(f"wa-verify:{_digest(code)}", str(user_id), ex=VERIFY_CODE_SECONDS)
        return code

    def take_verification(self, text: str) -> UUID | None:
        """The user a code in this text was issued to, once (GETDEL)."""
        for word in text.upper().split():
            if len(word) == 8 and all(c in CODE_ALPHABET for c in word):
                owner = self._redis.getdel(f"wa-verify:{_digest(word)}")
                if owner is not None:
                    return UUID(owner.decode() if isinstance(owner, bytes) else str(owner))
        return None


# --- The inbox --------------------------------------------------------------------------


@dataclass(frozen=True)
class Inbound:
    sender: str  # digits, as Meta sends wa_id
    text: str
    message_id: str


def parse_messages(payload: dict[str, Any]) -> list[Inbound]:
    """Text messages from a webhook body. Statuses and other types are ignored."""
    found: list[Inbound] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                if message.get("type") == "text":
                    text = str(message.get("text", {}).get("body", ""))[:2000]
                elif message.get("type") == "button":
                    text = str(message.get("button", {}).get("text", ""))[:200]
                else:
                    text = ""
                sender = str(message.get("from", ""))
                if sender.isdigit():
                    found.append(Inbound(sender, text, str(message.get("id", ""))))
    return found


@dataclass(frozen=True)
class Inbox:
    store: ApiStore
    state: InboxState
    sender: WhatsAppSender
    matches: Callable[[str, str], bool] = stop_code_matches

    def handle(self, message: Inbound) -> str:
        number, text = message.sender, message.text
        if self.state.over_limit("sender", number, SENDER_LIMIT):
            return "rate_limited"

        senders = self.store.whatsapp_senders(number)
        if not senders:
            return self._unknown(number, text)

        # The stop check comes before anything else (invariant 12). A number that failed
        # too often is not checked at all for an hour: no guessing the code (T28).
        if self.state.limited("stop", number, STOP_FAILURE_LIMIT):
            return "stop_locked"
        for user_id, _ in senders:
            code_hash = self.store.stop_code_hash(user_id)
            if code_hash and self.matches(code_hash, text):
                cancelled = self.store.pause(user_id, "whatsapp_stop")
                self.store.security_event(
                    user_id, "agent_stopped_by_code", {"cancelled": cancelled}
                )
                self.sender.send_text(number, PAUSED_REPLY)
                return "stopped"

        owner = next((u for u, role in senders if role == "owner"), None)
        if owner is None:
            # A backup number that did not send the right code: a failed stop attempt.
            for user_id, _ in senders:
                self.store.security_event(user_id, "stop_code_failed", {})
            self.state.over_limit("stop", number, STOP_FAILURE_LIMIT)
            return "backup_ignored"

        self.state.open_window(owner)
        user = self.store.user(owner)
        if user is not None and user.status != "active":
            self.sender.send_text(number, AGENT_PAUSED_REPLY)
            return "paused"
        self.sender.send_text(number, OWNER_REPLY)
        return "owner"

    def _unknown(self, number: str, text: str) -> str:
        if self.state.over_limit("verify", number, VERIFY_FAILURE_LIMIT):
            return "rate_limited"
        user_id = self.state.take_verification(text)
        if user_id is None:
            # UC-W7: no reply, nothing revealed. The number itself is not stored.
            self.store.security_event(None, "whatsapp_unknown_sender", {})
            return "dropped"
        if not self.store.bind_whatsapp_number(user_id, number):
            self.store.security_event(user_id, "whatsapp_number_taken", {})
            return "dropped"
        self.state.open_window(user_id)
        self.sender.send_text(number, VERIFIED_REPLY)
        return "verified"
