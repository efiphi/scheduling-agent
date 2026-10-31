"""WhatsApp inbox and webhook (whatsapp.py): T8, T28, UC-W7, UC-W8, invariant 12."""

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

import pytest
from api_fakes import FakeLogin, FakeRedis, FakeSessions, FakeStore
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis

from api.main import Deps, WhatsAppDeps, create_app
from api.whatsapp import (
    PAUSED_REPLY,
    STOP_FAILURE_LIMIT,
    VERIFIED_REPLY,
    Inbound,
    Inbox,
    InboxState,
    hash_stop_code,
    parse_messages,
    stop_code_matches,
    valid_signature,
)

OWNER = "972500000001"
BACKUP = "972500000002"
STRANGER = "972500000009"
SECRET = SecretStr("synthetic-app-secret")


@dataclass
class FakeState:
    counts: dict[tuple[str, str], int] = field(default_factory=dict)
    windows: set[UUID] = field(default_factory=set)
    codes: dict[str, UUID] = field(default_factory=dict)

    def over_limit(self, kind: str, key: str, limit: tuple[int, int]) -> bool:
        self.counts[(kind, key)] = self.counts.get((kind, key), 0) + 1
        return self.counts[(kind, key)] > limit[0]

    def limited(self, kind: str, key: str, limit: tuple[int, int]) -> bool:
        return self.counts.get((kind, key), 0) >= limit[0]

    def open_window(self, user_id: UUID) -> None:
        self.windows.add(user_id)

    def window_open(self, user_id: UUID) -> bool:
        return user_id in self.windows

    def start_verification(self, user_id: UUID) -> str:
        self.codes["K7P3Q9M2"] = user_id
        return "K7P3Q9M2"

    def take_verification(self, text: str) -> UUID | None:
        for word in text.upper().split():
            if word in self.codes:
                return self.codes.pop(word)
        return None


@dataclass
class FakeSender:
    sent: list[tuple[str, str]] = field(default_factory=list)

    def send_text(self, to: str, text: str) -> None:
        self.sent.append((to, text))


@dataclass
class Setup:
    inbox: Inbox
    store: FakeStore
    state: FakeState
    sender: FakeSender
    user: UUID


@pytest.fixture
def s() -> Setup:
    store, state, sender = FakeStore(), FakeState(), FakeSender()
    user = store.add_user()
    store.numbers[user] = OWNER
    store.backups[user] = [BACKUP]
    store.stop_hashes[user] = hash_stop_code("purple elephant 42")
    inbox = Inbox(store=store, state=cast(InboxState, state), sender=sender)
    return Setup(inbox, store, state, sender, user)


def msg(sender: str, text: str) -> Inbound:
    return Inbound(sender=sender, text=text, message_id="wamid.1")


# --- Unknown numbers --------------------------------------------------------------------


def test_uc_w7_an_unknown_number_gets_no_reply_and_nothing_happens(s: Setup) -> None:
    assert s.inbox.handle(msg(STRANGER, "what meetings does Efi have tomorrow?")) == "dropped"
    assert s.sender.sent == []
    assert (None, "whatsapp_unknown_sender") in s.store.events


def test_inbound_verification_binds_the_number_once(s: Setup) -> None:
    newcomer = s.store.add_user("new@example.com")
    code = s.state.start_verification(newcomer)
    assert s.inbox.handle(msg(STRANGER, f"אימות {code}")) == "verified"
    assert s.store.numbers[newcomer] == STRANGER
    assert s.sender.sent == [(STRANGER, VERIFIED_REPLY)]
    # The code works once.
    assert s.inbox.handle(msg("972500000008", code)) == "dropped"


def test_t28_unknown_numbers_cannot_guess_verification_codes_forever(s: Setup) -> None:
    for _ in range(5):
        s.inbox.handle(msg(STRANGER, "AAAAAAAA"))
    assert s.inbox.handle(msg(STRANGER, "BBBBBBBB")) == "rate_limited"


# --- The stop code ------------------------------------------------------------------------


@pytest.mark.parametrize("sender", [OWNER, BACKUP])
def test_uc_w8_the_stop_code_pauses_and_cancels_from_the_own_or_a_backup_number(
    s: Setup, sender: str
) -> None:
    s.store.add_action(s.user)
    assert s.inbox.handle(msg(sender, "  Purple   ELEPHANT 42 ")) == "stopped"
    assert s.store.users[s.user].status == "paused"
    assert s.store.actions(s.user, "pending") == []
    assert s.sender.sent == [(sender, PAUSED_REPLY)]


def test_t8_the_stop_code_from_an_unknown_number_does_nothing(s: Setup) -> None:
    # Something you know is not enough: it must come from a registered phone too.
    assert s.inbox.handle(msg(STRANGER, "purple elephant 42")) == "dropped"
    assert s.store.users[s.user].status == "active"


def test_a_backup_number_can_only_stop_nothing_else(s: Setup) -> None:
    assert s.inbox.handle(msg(BACKUP, "approve everything please")) == "backup_ignored"
    assert s.sender.sent == []
    assert (s.user, "stop_code_failed") in s.store.events


def test_t28_after_too_many_wrong_codes_even_the_right_one_is_not_checked(s: Setup) -> None:
    for _ in range(STOP_FAILURE_LIMIT[0]):
        s.inbox.handle(msg(BACKUP, "wrong guess"))
    assert s.inbox.handle(msg(BACKUP, "purple elephant 42")) == "stop_locked"
    assert s.store.users[s.user].status == "active"


def test_stop_code_is_stored_as_argon2id_not_plain_text() -> None:
    stored = hash_stop_code("purple elephant 42")
    assert stored.startswith("$argon2id$") and "purple" not in stored
    assert stop_code_matches(stored, "PURPLE elephant 42")
    assert not stop_code_matches(stored, "purple elephant 43")


# --- The owner ---------------------------------------------------------------------------


def test_the_owner_opens_the_24_hour_window(s: Setup) -> None:
    assert s.inbox.handle(msg(OWNER, "היי")) == "owner"
    assert s.state.window_open(s.user)


def test_a_paused_agent_says_so_and_does_nothing(s: Setup) -> None:
    s.store.pause(s.user, "web")
    assert s.inbox.handle(msg(OWNER, "תאשר הכל")) == "paused"


def test_t28_a_flood_from_one_number_is_dropped_early(s: Setup) -> None:
    for _ in range(20):
        s.inbox.handle(msg(OWNER, "hi"))
    assert s.inbox.handle(msg(OWNER, "hi")) == "rate_limited"


# --- The webhook ---------------------------------------------------------------------------


def signed(body: bytes) -> str:
    return (
        "sha256=" + hmac.new(SECRET.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    )


def test_signature_check() -> None:
    body = b'{"entry": []}'
    assert valid_signature(SECRET, body, signed(body))
    assert not valid_signature(SECRET, body + b" ", signed(body))
    assert not valid_signature(SECRET, body, None)
    assert not valid_signature(SECRET, body, "sha256=" + "0" * 64)


def webhook_client(s: Setup) -> TestClient:
    wa = WhatsAppDeps(
        inbox=s.inbox,
        state=cast(InboxState, s.state),
        app_secret=SECRET,
        verify_token=SecretStr("synthetic-verify"),
        agent_number="+1 555 0100",
    )
    deps = Deps(
        login=FakeLogin(),
        sessions=FakeSessions(),
        store=s.store,
        redis=cast(Redis, FakeRedis()),
        web_app_url="http://localhost:5173/",
        cookie_secure=True,
        whatsapp=wa,
    )
    return TestClient(create_app(deps))


def payload(sender: str, text: str) -> dict[str, Any]:
    message = {"from": sender, "id": "wamid.1", "type": "text", "text": {"body": text}}
    return {"entry": [{"changes": [{"value": {"messages": [message]}}]}]}


def test_t8_a_webhook_without_metas_signature_is_refused_unread(s: Setup) -> None:
    body = json.dumps(payload(OWNER, "purple elephant 42")).encode()
    client = webhook_client(s)
    assert (
        client.post(
            "/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=00"}
        ).status_code
        == 403
    )
    assert s.store.users[s.user].status == "active"


def test_a_signed_webhook_is_processed(s: Setup) -> None:
    body = json.dumps(payload(OWNER, "purple elephant 42")).encode()
    response = webhook_client(s).post(
        "/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": signed(body)}
    )
    assert response.status_code == 200
    assert s.store.users[s.user].status == "paused"


def test_handshake_needs_our_verify_token(s: Setup) -> None:
    client = webhook_client(s)
    good = {"hub.mode": "subscribe", "hub.verify_token": "synthetic-verify", "hub.challenge": "42"}
    assert client.get("/whatsapp/webhook", params=good).text == "42"
    assert (
        client.get("/whatsapp/webhook", params={**good, "hub.verify_token": "x"}).status_code == 403
    )


def test_only_text_messages_with_a_numeric_sender_are_read() -> None:
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": OWNER, "type": "text", "text": {"body": "hi"}},
                                {"from": OWNER, "type": "image", "image": {}},
                                {"from": "not-a-number", "type": "text", "text": {"body": "x"}},
                            ],
                            "statuses": [{"status": "delivered"}],
                        }
                    }
                ]
            }
        ]
    }
    assert [(m.sender, m.text) for m in parse_messages(body)] == [(OWNER, "hi"), (OWNER, "")]


def test_the_public_webhook_app_exposes_nothing_but_the_webhook(s: Setup) -> None:
    from api.main import create_webhook_app

    wa = WhatsAppDeps(
        inbox=s.inbox,
        state=cast(InboxState, s.state),
        app_secret=SECRET,
        verify_token=SecretStr("synthetic-verify"),
        agent_number="",
    )
    deps = Deps(
        login=FakeLogin(),
        sessions=FakeSessions(),
        store=s.store,
        redis=cast(Redis, FakeRedis()),
        web_app_url="",
        cookie_secure=True,
        whatsapp=wa,
    )
    client = TestClient(create_webhook_app(deps))
    assert client.get("/healthz").status_code == 200
    for path in ("/me", "/actions", "/auth/google/login", "/security", "/docs", "/openapi.json"):
        assert client.get(path).status_code == 404
    body = json.dumps(payload(OWNER, "hi")).encode()
    assert (
        client.post(
            "/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": signed(body)}
        ).status_code
        == 200
    )
