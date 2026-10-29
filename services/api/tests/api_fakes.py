"""In-memory stand-ins for Google, Redis and the database. Synthetic data only."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from api.google_login import Identity, LoginError
from api.sessions import LoginState, Session, SessionData, new_token
from api.store import Action, ApproveResult, Question, User

USER_EMAIL = "demo-user@example.com"
HASH = "sha256:" + "a" * 64


@dataclass
class FakeLogin:
    identity: Identity | LoginError = field(default_factory=lambda: Identity(USER_EMAIL, True))
    exchanged: list[tuple[str, str]] = field(default_factory=list)

    def authorization_url(self, state: str, code_verifier: str) -> str:
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
    audits: list[tuple[UUID, str]] = field(default_factory=list)

    def add_user(self, email: str = USER_EMAIL, status: str = "active") -> UUID:
        user_id = uuid4()
        self.users[user_id] = User(user_id, email, status, False)
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

    def approve(self, user_id: UUID, action_id: UUID, content_hash: str) -> ApproveResult:
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


@dataclass
class FakeRedis:
    streams: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def xadd(self, name: str, fields: dict[str, str], **_: Any) -> str:
        self.streams.setdefault(name, []).append(fields)
        return "0-1"
