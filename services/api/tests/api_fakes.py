"""In-memory stand-ins for Google, Redis and the database. Synthetic data only."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from api.google_login import Identity, LoginError
from api.sessions import LoginState, Session, SessionData, new_token
from api.store import Action, AdminUser, ApproveResult, Invite, Question, User

USER_EMAIL = "demo-user@example.com"
HASH = "sha256:" + "a" * 64


@dataclass
class FakeLogin:
    identity: Identity | LoginError = field(default_factory=lambda: Identity(USER_EMAIL, True))
    exchanged: list[tuple[str, str]] = field(default_factory=list)
    hints: list[str | None] = field(default_factory=list)

    def authorization_url(
        self, state: str, code_verifier: str, login_hint: str | None = None
    ) -> str:
        self.hints.append(login_hint)
        return f"https://accounts.example/auth?state={state}"

    def exchange(self, code: str, code_verifier: str) -> Identity:
        self.exchanged.append((code, code_verifier))
        if isinstance(self.identity, LoginError):
            raise self.identity
        return self.identity


@dataclass
class FakeSessions:
    states: dict[str, LoginState] = field(default_factory=dict)
    sessions: dict[str, Session] = field(default_factory=dict)

    def put_login_state(self, state: str, login: LoginState) -> None:
        self.states[state] = login

    def take_login_state(self, state: str) -> LoginState | None:
        return self.states.pop(state, None)

    def create(self, user_id: UUID) -> Session:
        now = datetime.now(UTC).timestamp()
        session = Session(
            new_token(),
            SessionData(
                user_id=user_id, csrf_token=new_token(), created_at=now, authenticated_at=now
            ),
        )
        self.sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def delete_all(self, user_id: UUID) -> int:
        mine = [k for k, s in self.sessions.items() if s.data.user_id == user_id]
        for k in mine:
            del self.sessions[k]
        return len(mine)


@dataclass
class FakeStore:
    users: dict[UUID, User] = field(default_factory=dict)
    actions_by_id: dict[UUID, tuple[UUID, Action]] = field(default_factory=dict)
    approvals: set[UUID] = field(default_factory=set)
    channels: dict[UUID, str] = field(default_factory=dict)
    audits: list[tuple[UUID, str]] = field(default_factory=list)
    numbers: dict[UUID, str] = field(default_factory=dict)
    backups: dict[UUID, list[str]] = field(default_factory=dict)
    stop_hashes: dict[UUID, str] = field(default_factory=dict)
    paused: list[tuple[UUID, str]] = field(default_factory=list)
    events: list[tuple[UUID | None, str]] = field(default_factory=list)
    # token hash -> (admin, invite); mirrors migration 0007's rules
    invite_rows: dict[str, tuple[UUID, Invite]] = field(default_factory=dict)

    def add_user(
        self, email: str = USER_EMAIL, status: str = "active", *, is_admin: bool = False
    ) -> UUID:
        user_id = uuid4()
        self.users[user_id] = User(user_id, email, status, is_admin)
        return user_id

    def add_action(self, user_id: UUID, *, expires_in: timedelta = timedelta(hours=4)) -> UUID:
        action_id = uuid4()
        now = datetime.now(UTC)
        payload = {
            "to": ["dana@example.org"],
            "subject": "Re: Call?",
            "body": "Hi",
            "slots": [{"start": now.isoformat(), "end": (now + timedelta(minutes=30)).isoformat()}],
        }
        self.actions_by_id[action_id] = (
            user_id,
            Action(action_id, "reply_with_slots", "pending", payload, HASH, now + expires_in, now),
        )
        return action_id

    def find_user(self, email: str) -> UUID | None:
        return next((u.user_id for u in self.users.values() if u.email == email), None)

    def user(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    def actions(self, user_id: UUID, status: str) -> list[Action]:
        return [
            a for owner, a in self.actions_by_id.values() if owner == user_id and a.status == status
        ]

    def action(self, user_id: UUID, action_id: UUID) -> Action | None:
        owner, found = self.actions_by_id.get(action_id, (None, None))
        return found if owner == user_id else None

    def approve(
        self, user_id: UUID, action_id: UUID, content_hash: str, channel: str = "web"
    ) -> ApproveResult:
        found = self.action(user_id, action_id)
        if found is None:
            return ApproveResult.NOT_FOUND
        if found.status != "pending":
            return ApproveResult.NOT_PENDING
        if found.expires_at <= datetime.now(UTC):
            return ApproveResult.EXPIRED
        if content_hash != found.content_hash:
            return ApproveResult.HASH_MISMATCH
        self.approvals.add(action_id)
        self.channels[action_id] = channel
        self.actions_by_id[action_id] = (
            user_id,
            Action(**{**found.__dict__, "status": "approved"}),
        )
        return ApproveResult.APPROVED

    def reject(self, user_id: UUID, action_id: UUID) -> bool:
        found = self.action(user_id, action_id)
        if found is None or found.status != "pending":
            return False
        self.actions_by_id[action_id] = (
            user_id,
            Action(**{**found.__dict__, "status": "rejected"}),
        )
        return True

    def questions(self, user_id: UUID) -> list[Question]:
        return []

    def dismiss_question(self, user_id: UUID, question_id: UUID) -> bool:
        return False

    def audit(self, user_id: UUID, action: str, details: dict[str, Any]) -> None:
        self.audits.append((user_id, action))

    # --- WhatsApp ---------------------------------------------------------------------

    def whatsapp_senders(self, number: str) -> list[tuple[UUID, str]]:
        found = [(u, "owner") for u, n in self.numbers.items() if n == number]
        found += [(u, "backup") for u, ns in self.backups.items() if number in ns]
        return found

    def stop_code_hash(self, user_id: UUID) -> str | None:
        return self.stop_hashes.get(user_id)

    def whatsapp_number(self, user_id: UUID) -> str | None:
        return self.numbers.get(user_id)

    def whatsapp_verified(self, user_id: UUID) -> bool:
        return user_id in self.numbers

    def set_stop_code_hash(self, user_id: UUID, code_hash: str) -> None:
        self.stop_hashes[user_id] = code_hash

    def bind_whatsapp_number(self, user_id: UUID, number: str) -> bool:
        if number in self.numbers.values():
            return False
        self.numbers[user_id] = number
        return True

    def backup_numbers(self, user_id: UUID) -> list[str]:
        return sorted(self.backups.get(user_id, []))

    def set_backup_numbers(self, user_id: UUID, numbers: list[str]) -> None:
        self.backups[user_id] = list(numbers)

    def pause(self, user_id: UUID, channel: str) -> int:
        user = self.users[user_id]
        self.users[user_id] = User(user.user_id, user.email, "paused", user.is_admin)
        pending = [
            a
            for owner, a in self.actions_by_id.values()
            if owner == user_id and a.status == "pending"
        ]
        for a in pending:
            self.actions_by_id[a.action_id] = (
                user_id,
                Action(**{**a.__dict__, "status": "rejected"}),
            )
        self.paused.append((user_id, channel))
        return len(pending)

    def resume(self, user_id: UUID) -> None:
        user = self.users[user_id]
        self.users[user_id] = User(user.user_id, user.email, "active", user.is_admin)

    def security_event(self, user_id: UUID | None, kind: str, details: dict[str, Any]) -> None:
        self.events.append((user_id, kind))

    # --- Invites ----------------------------------------------------------------------

    def _live(self, invite: Invite) -> bool:
        return invite.status == "pending" and invite.expires_at > datetime.now(UTC)

    def create_invite(
        self, admin_id: UUID, email: str, token_hash: str, expires_at: datetime
    ) -> Invite | None:
        if not self.users[admin_id].is_admin:
            return None
        invite = Invite(uuid4(), email.lower(), "pending", expires_at, datetime.now(UTC))
        self.invite_rows[token_hash] = (admin_id, invite)
        return invite

    def invites(self, admin_id: UUID) -> list[Invite]:
        return [i for a, i in self.invite_rows.values() if a == admin_id]

    def revoke_invite(self, admin_id: UUID, invite_id: UUID) -> bool:
        for h, (a, i) in self.invite_rows.items():
            if a == admin_id and i.invite_id == invite_id and i.status == "pending":
                self.invite_rows[h] = (a, Invite(**{**i.__dict__, "status": "revoked"}))
                return True
        return False

    def invite_email(self, token_hash: str) -> str | None:
        found = self.invite_rows.get(token_hash)
        return found[1].email if found and self._live(found[1]) else None

    def accept_invite(self, token_hash: str, email: str) -> UUID | None:
        found = self.invite_rows.get(token_hash)
        if not found or not self._live(found[1]) or found[1].email != email.lower():
            return None
        if self.find_user(email.lower()) is not None:
            return None
        admin, invite = found
        self.invite_rows[token_hash] = (admin, Invite(**{**invite.__dict__, "status": "used"}))
        return self.add_user(email.lower())

    google: dict[UUID, str] = field(default_factory=dict)

    def google_status(self, user_id: UUID) -> Any:
        return self.google.get(user_id, "not_connected")

    def admin_users(self, admin_id: UUID) -> list[AdminUser]:
        if not self.users[admin_id].is_admin:
            return []
        now = datetime.now(UTC)
        return [
            AdminUser(u.email, u.status, u.is_admin, u.user_id in self.numbers, "connected", now)
            for u in self.users.values()
        ]


@dataclass
class FakeRedis:
    streams: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def xadd(self, name: str, fields: dict[str, str], **_: Any) -> str:
        self.streams.setdefault(name, []).append(fields)
        return "0-1"

    counters: dict[str, int] = field(default_factory=dict)
    queued: list[Any] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)

    # Plain keys, for the Google connect ticket (shared.connect_ticket).
    def set(self, name: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and name in self.values:
            return False
        self.values[name] = value
        return True

    def getdel(self, name: str) -> str | None:
        return self.values.pop(name, None)

    # Counters and a pipeline, for the alert relay's hourly cap. Expiry is not modelled.
    def pipeline(self) -> "FakeRedis":
        return self

    def incr(self, name: str) -> None:
        self.counters[name] = self.counters.get(name, 0) + 1
        self.queued.append(self.counters[name])

    def expire(self, name: str, seconds: int, **_: Any) -> None:
        self.queued.append(True)

    def execute(self) -> list[Any]:
        results, self.queued = self.queued, []
        return results
