"""Owner-run cleanup of skipped emails (UC-M8: kept 7 days, sender/subject/time only)."""

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from db.maintenance import purge_skipped_emails

pytestmark = pytest.mark.db


@pytest.fixture
def user(owner: Engine) -> Iterator[UUID]:
    uid = uuid4()
    with owner.begin() as conn:
        conn.execute(
            text("INSERT INTO app.users (user_id, email) VALUES (:id, :email)"),
            {"id": uid, "email": f"user-{uid}@example.com"},
        )
        for age_days, subject in ((8, "old"), (6, "recent")):
            conn.execute(
                text(
                    "INSERT INTO app.skipped_emails (user_id, sender, subject, received_at)"
                    " VALUES (:id, 'news@example.org', :subject,"
                    " now() - make_interval(days => :age))"
                ),
                {"id": uid, "subject": subject, "age": age_days},
            )
    yield uid
    with owner.begin() as conn:
        conn.execute(text("DELETE FROM app.users WHERE user_id = :id"), {"id": uid})


def test_purge_keeps_the_last_seven_days_only(owner: Engine, user: UUID) -> None:
    assert purge_skipped_emails(owner) >= 1
    with owner.begin() as conn:
        subjects = conn.execute(
            text("SELECT subject FROM app.skipped_emails WHERE user_id = :id"), {"id": user}
        ).scalars()
        assert list(subjects) == ["recent"]
        details = conn.execute(
            text(
                "SELECT details FROM app.audit_log WHERE action = 'skipped_emails_purged'"
                " ORDER BY event_id DESC LIMIT 1"
            )
        ).scalar_one()
    assert details["days"] == 7 and details["deleted"] >= 1


def test_the_gateway_cannot_delete_skipped_emails(gateway: Engine, user: UUID) -> None:
    # Retention is enforced by the owner, not by the service that writes the rows.
    with pytest.raises(Exception, match="permission denied"), gateway.begin() as conn:
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user)})
        conn.execute(text("DELETE FROM app.skipped_emails WHERE user_id = :u"), {"u": user})
