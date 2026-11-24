"""Invites in Postgres itself (migration 0007): who may invite, and accepting exactly once (T14).

Every test runs as the real api_service role, so the database must refuse whatever the
application code might get wrong. Synthetic addresses only.
"""

import hashlib
import secrets
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from db.session import set_user_context as as_user

pytestmark = pytest.mark.db

INVITEE = "new-member@example.com"


def token_hash() -> str:
    return hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()


@pytest.fixture
def admin(owner: Engine, seed: Any) -> Iterator[UUID]:
    """User A becomes the admin; user B stays an ordinary user."""
    with owner.begin() as conn:
        conn.execute(
            text("UPDATE app.users SET is_admin = true WHERE user_id = :u"), {"u": seed.user_a}
        )
    yield seed.user_a
    with owner.begin() as conn:
        conn.execute(text("DELETE FROM app.users WHERE email = :e"), {"e": INVITEE})
        conn.execute(text("DELETE FROM app.audit_log WHERE action = 'invite_accepted'"))


def invite(
    api: Engine, inviter: UUID, h: str, email: str = INVITEE, expires: str = "3 days"
) -> None:
    with api.begin() as conn:
        as_user(conn, inviter)
        conn.execute(
            text(
                "INSERT INTO app.invites (user_id, email, token_hash, expires_at)"
                " VALUES (:u, :e, :h, now() + CAST(:x AS interval))"
            ),
            {"u": inviter, "e": email, "h": h, "x": expires},
        )


def accept(api: Engine, h: str, email: str = INVITEE) -> UUID | None:
    with api.begin() as conn:  # no user context: this happens before the first login
        found = conn.execute(
            text("SELECT app.accept_invite(:h, :e)"), {"h": h, "e": email}
        ).scalar_one_or_none()
    return None if found is None else UUID(str(found))


# --- Who may invite -----------------------------------------------------------------------


def test_t14_an_admin_can_invite(api: Engine, admin: UUID) -> None:
    h = token_hash()
    invite(api, admin, h)
    with api.begin() as conn:
        assert conn.execute(text("SELECT app.invite_email(:h)"), {"h": h}).scalar_one() == INVITEE


def test_t14_an_ordinary_user_cannot_invite(api: Engine, admin: UUID, seed: Any) -> None:
    with pytest.raises(ProgrammingError, match="row-level security policy"):
        invite(api, seed.user_b, token_hash())


def test_t14_cannot_invite_in_another_users_name(api: Engine, admin: UUID, seed: Any) -> None:
    with pytest.raises(ProgrammingError, match="row-level security policy"), api.begin() as conn:
        as_user(conn, seed.user_b)
        conn.execute(
            text(
                "INSERT INTO app.invites (user_id, email, token_hash, expires_at)"
                " VALUES (:admin, :e, :h, now() + interval '1 day')"
            ),
            {"admin": admin, "e": INVITEE, "h": token_hash()},
        )


def test_t14_the_api_cannot_mark_an_invite_used(api: Engine, admin: UUID) -> None:
    h = token_hash()
    invite(api, admin, h)
    with pytest.raises(ProgrammingError, match="permission denied"), api.begin() as conn:
        as_user(conn, admin)
        conn.execute(text("UPDATE app.invites SET used_at = now() WHERE token_hash = :h"), {"h": h})


def test_t14_only_a_hash_fits_the_token_column(api: Engine, admin: UUID) -> None:
    with pytest.raises(Exception, match="invites_token_hash_sha256"):
        invite(api, admin, "the-raw-token-itself")


# --- Accepting --------------------------------------------------------------------------


def test_t14_accepting_creates_the_user_once(api: Engine, owner: Engine, admin: UUID) -> None:
    h = token_hash()
    invite(api, admin, h)
    user = accept(api, h, INVITEE.upper())  # Google may return any case
    assert user is not None
    assert accept(api, h) is None  # single use
    with owner.begin() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.settings WHERE user_id = :u"), {"u": user}
            ).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                text("SELECT used_by FROM app.invites WHERE token_hash = :h"), {"h": h}
            ).scalar_one()
            == user
        )
    with api.begin() as conn:
        assert conn.execute(text("SELECT app.invite_email(:h)"), {"h": h}).scalar_one() is None


def test_t14_invite_is_bound_to_its_email(api: Engine, admin: UUID) -> None:
    h = token_hash()
    invite(api, admin, h)
    assert accept(api, h, "someone-else@example.com") is None
    assert accept(api, h) is not None  # the refusal did not use it up


def test_t14_an_expired_invite_is_refused(api: Engine, admin: UUID) -> None:
    h = token_hash()
    invite(api, admin, h, expires="-1 minute")
    assert accept(api, h) is None


def test_t14_a_revoked_invite_is_refused(api: Engine, admin: UUID) -> None:
    h = token_hash()
    invite(api, admin, h)
    with api.begin() as conn:
        as_user(conn, admin)
        conn.execute(
            text("UPDATE app.invites SET revoked_at = now() WHERE token_hash = :h"), {"h": h}
        )
    assert accept(api, h) is None


def test_t14_two_logins_racing_with_one_link_create_one_user(api: Engine, admin: UUID) -> None:
    h = token_hash()
    invite(api, admin, h)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: accept(api, h), range(4)))
    assert len([r for r in results if r is not None]) == 1


# --- The admin's list ---------------------------------------------------------------------


def test_admin_users_shows_setup_state_only_to_an_admin(
    api: Engine, admin: UUID, seed: Any
) -> None:
    with api.begin() as conn:
        as_user(conn, admin)
        rows = conn.execute(text("SELECT * FROM app.admin_users()")).mappings().all()
    by_email = {r["email"]: r for r in rows}
    assert by_email[f"user-{seed.user_a}@example.com"]["google_status"] == "connected"
    assert by_email[f"user-{seed.user_b}@example.com"]["google_status"] == "not_connected"
    assert set(rows[0].keys()) == {
        "email",
        "status",
        "is_admin",
        "whatsapp_verified",
        "google_status",
        "created_at",
    }
    with api.begin() as conn:
        as_user(conn, seed.user_b)  # not an admin
        assert conn.execute(text("SELECT * FROM app.admin_users()")).all() == []


def test_gateway_cannot_touch_invites(gateway: Engine, admin: UUID) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"), gateway.begin() as conn:
        conn.execute(text("SELECT app.invite_email('x')"))
