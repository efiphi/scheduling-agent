"""In-memory stand-ins for Redis, Google and the database, so the connect flow is tested
without network access. All values are synthetic."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from google_gateway.google_oauth import SCOPES, GoogleGrant
from google_gateway.oauth_state import PendingConnect
from google_gateway.token_crypto import EncryptedToken

USER_EMAIL = "demo-user@example.com"
REFRESH_TOKEN = "synthetic-refresh-token"  # noqa: S105 - fake value, not a credential
CODE = "synthetic-authorization-code"


class FakeStates:
    def __init__(self) -> None:
        self.items: dict[str, PendingConnect] = {}

    def put(self, state: str, pending: PendingConnect) -> None:
        self.items[state] = pending

    def take(self, state: str) -> PendingConnect | None:
        return self.items.pop(state, None)


def grant(**changes: Any) -> GoogleGrant:
    values: dict[str, Any] = {
        "refresh_token": REFRESH_TOKEN,
        "scopes": SCOPES,
        "email": USER_EMAIL,
        "email_verified": True,
    }
    values.update(changes)
    return GoogleGrant(**values)


@dataclass
class FakeGoogle:
    result: GoogleGrant | Exception = field(default_factory=grant)
    exchanged: list[tuple[str, str]] = field(default_factory=list)

    def authorization_url(self, state: str, code_verifier: str) -> str:
        return f"https://accounts.example/consent?state={state}"

    def exchange(self, code: str, code_verifier: str) -> GoogleGrant:
        self.exchanged.append((code, code_verifier))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class FakeRepo:
    emails: dict[UUID, str] = field(default_factory=dict)
    saved: dict[UUID, tuple[EncryptedToken, list[str]]] = field(default_factory=dict)
    audits: list[tuple[UUID, str, dict[str, Any]]] = field(default_factory=list)
    security_events: list[tuple[UUID | None, str, dict[str, Any]]] = field(default_factory=list)

    def user_email(self, user_id: UUID) -> str | None:
        return self.emails.get(user_id)

    def save_credentials(self, user_id: UUID, token: EncryptedToken, scopes: list[str]) -> None:
        self.saved[user_id] = (token, scopes)
        self.audits.append((user_id, "google_connected", {"scopes": scopes}))

    def load_credentials(self, user_id: UUID) -> tuple[EncryptedToken, list[str]] | None:
        return self.saved.get(user_id)

    def audit(self, user_id: UUID, action: str, details: dict[str, Any]) -> None:
        self.audits.append((user_id, action, details))

    def security_event(self, user_id: UUID | None, kind: str, details: dict[str, Any]) -> None:
        self.security_events.append((user_id, kind, details))
