"""SqlCredentialRepository against the real database, as the gateway_service role (T13, T16)."""

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from google_gateway.credentials_store import SqlCredentialRepository
from google_gateway.token_crypto import KEY_BYTES, TokenCipher

pytestmark = pytest.mark.db

TOKEN = "synthetic-refresh-token-for-db-tests"  # noqa: S105 - fake value, not a credential
SCOPES = ["openid", "https://www.googleapis.com/auth/gmail.readonly"]
CIPHER = TokenCipher({1: bytes([9]) * KEY_BYTES})


@pytest.fixture
def users(owner: Engine) -> Iterator[tuple[UUID, UUID]]:
    a, b = uuid4(), uuid4()
    with owner.begin() as conn:
        for uid in (a, b):
            conn.execute(
                text("INSERT INTO app.users (user_id, email) VALUES (:id, :email)"),
                {"id": uid, "email": f"user-{uid}@example.com"},
            )
    yield a, b
    with owner.begin() as conn:
        for uid in (a, b):
            conn.execute(text("DELETE FROM app.users WHERE user_id = :id"), {"id": uid})
            conn.execute(text("DELETE FROM app.audit_log WHERE user_id = :id"), {"id": uid})
            conn.execute(text("DELETE FROM app.security_events WHERE user_id = :id"), {"id": uid})


def test_t16_saves_encrypted_token_and_reads_it_back(
    gateway: Engine, owner: Engine, users: tuple[UUID, UUID]
) -> None:
    a, _ = users
    repo = SqlCredentialRepository(gateway)
    repo.save_credentials(a, CIPHER.encrypt(TOKEN, a), SCOPES)

    loaded = repo.load_credentials(a)
    assert loaded is not None
    encrypted, scopes = loaded
    assert CIPHER.decrypt(encrypted, a) == TOKEN
    assert scopes == SCOPES
    with owner.begin() as conn:
        stored = conn.execute(
            text("SELECT encrypted_refresh_token FROM app.google_credentials WHERE user_id = :a"),
            {"a": a},
        ).scalar_one()
        actions = conn.execute(
            text("SELECT action FROM app.audit_log WHERE user_id = :a"), {"a": a}
        ).scalars()
        assert TOKEN.encode() not in bytes(stored)
        assert list(actions) == ["google_connected"]


def test_reconnect_replaces_the_token(gateway: Engine, users: tuple[UUID, UUID]) -> None:
    a, _ = users
    repo = SqlCredentialRepository(gateway)
    repo.save_credentials(a, CIPHER.encrypt("old-synthetic-token", a), SCOPES)
    repo.save_credentials(a, CIPHER.encrypt(TOKEN, a), SCOPES)
    loaded = repo.load_credentials(a)
    assert loaded is not None
    assert CIPHER.decrypt(loaded[0], a) == TOKEN


def test_t13_each_user_sees_only_their_own_rows(gateway: Engine, users: tuple[UUID, UUID]) -> None:
    a, b = users
    repo = SqlCredentialRepository(gateway)
    repo.save_credentials(a, CIPHER.encrypt(TOKEN, a), SCOPES)
    assert repo.load_credentials(b) is None
    assert repo.user_email(a) == f"user-{a}@example.com"
    assert repo.user_email(b) == f"user-{b}@example.com"


def test_security_events_with_and_without_a_user(
    gateway: Engine, owner: Engine, users: tuple[UUID, UUID]
) -> None:
    a, _ = users
    repo = SqlCredentialRepository(gateway)
    repo.security_event(a, "google_account_mismatch", {})
    repo.security_event(None, "oauth_invalid_state", {"test_marker": str(a)})
    with owner.begin() as conn:
        kinds = conn.execute(
            text("SELECT kind FROM app.security_events WHERE user_id = :a"), {"a": a}
        ).scalars()
        assert list(kinds) == ["google_account_mismatch"]
        anonymous = conn.execute(
            text(
                "DELETE FROM app.security_events"
                " WHERE user_id IS NULL AND details->>'test_marker' = :m RETURNING kind"
            ),
            {"m": str(a)},
        ).scalars()
        assert list(anonymous) == ["oauth_invalid_state"]
