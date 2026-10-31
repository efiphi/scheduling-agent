"""Security settings in the api (ADR-014, invariant 12): fresh login, masking, pause."""

import time
from dataclasses import replace

from api_fakes import FakeStore
from test_auth_and_approvals import Setup, s  # noqa: F401 - the fixture

from api.whatsapp import stop_code_matches


def make_login_old(setup: Setup) -> None:
    for key, session in list(setup.sessions.sessions.items()):
        old = session.data.model_copy(update={"authenticated_at": time.time() - 3600})
        setup.sessions.sessions[key] = replace(session, data=old)


def test_setting_the_stop_code_needs_a_fresh_login(s: Setup) -> None:  # noqa: F811
    csrf = s.log_in()
    ok = s.client.put(
        "/security/stop-code", json={"code": "purple elephant 42"}, headers={"X-CSRF-Token": csrf}
    )
    assert ok.status_code == 200
    assert stop_code_matches(s.store.stop_hashes[s.user], "purple elephant 42")
    make_login_old(s)
    stale = s.client.put(
        "/security/stop-code", json={"code": "another code"}, headers={"X-CSRF-Token": csrf}
    )
    assert stale.status_code == 401 and stale.json()["detail"] == "login again"


def test_backup_numbers_are_normalised_and_shown_masked(s: Setup) -> None:  # noqa: F811
    csrf = s.log_in()
    response = s.client.put(
        "/security/backup-numbers",
        json={"numbers": ["+972-50-000-0002"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert s.store.backups[s.user] == ["972500000002"]
    shown = s.client.get("/security").json()
    assert shown["backup_numbers"] == ["…0002"]
    assert "972500000002" not in str(shown)


def test_bad_or_too_many_backup_numbers_are_refused(s: Setup) -> None:  # noqa: F811
    csrf = s.log_in()
    for numbers in (["not a number"], ["123"], ["972500000002", "972500000003", "972500000004"]):
        response = s.client.put(
            "/security/backup-numbers", json={"numbers": numbers}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 422


def test_pause_from_the_web_and_resume_only_after_a_fresh_login(s: Setup) -> None:  # noqa: F811
    csrf = s.log_in()
    s.store.add_action(s.user)
    assert s.client.post("/security/pause", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert s.store.users[s.user].status == "paused"
    assert s.store.actions(s.user, "pending") == []
    make_login_old(s)
    assert s.client.post("/security/resume", headers={"X-CSRF-Token": csrf}).status_code == 401
    assert s.store.users[s.user].status == "paused"


def test_whatsapp_routes_are_absent_when_whatsapp_is_not_configured(s: Setup) -> None:  # noqa: F811
    csrf = s.log_in()
    assert s.client.post("/whatsapp/verify", headers={"X-CSRF-Token": csrf}).status_code == 404
    assert isinstance(s.store, FakeStore)
