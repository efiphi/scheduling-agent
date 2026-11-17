"""Alerts to the owner's WhatsApp: who may post, what is sent, and how often (ADR-022)."""

from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

import pytest
from api_fakes import FakeRedis
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis
from test_whatsapp import FakeSender

from api.alert_relay import MAX_MESSAGES_PER_HOUR, AlertRelay, create_alert_relay_app
from api.whatsapp import InboxState

OWNER = UUID("00000000-0000-0000-0000-0000000000aa")
NUMBER = "15550000001"
TOKEN = "synthetic-relay-token"  # noqa: S105 - a test value, not a secret


@dataclass
class FakeState:
    open_window: bool = True
    opened: list[UUID] = field(default_factory=list)

    def window_open(self, user_id: UUID) -> bool:
        return self.open_window


def alert(status: str = "firing", **annotations: str) -> dict[str, Any]:
    return {
        "status": status,
        "labels": {"alertname": "StopCodeGuessing", "severity": "critical", "threat": "T28"},
        "annotations": {"summary_he": "ניסיונות חוזרים לנחש את קוד העצירה", **annotations},
    }


@dataclass
class Setup:
    client: TestClient
    sender: FakeSender
    state: FakeState


def make(template: str | None = "system_alert", window: bool = True) -> Setup:
    sender, state = FakeSender(), FakeState(open_window=window)
    relay = AlertRelay(
        sender=sender,
        state=cast(InboxState, state),
        redis=cast(Redis, FakeRedis()),
        owner_id=OWNER,
        owner_number=NUMBER,
        template=template,
    )
    return Setup(TestClient(create_alert_relay_app(relay, SecretStr(TOKEN))), sender, state)


def post(s: Setup, *alerts: dict[str, Any], token: str = TOKEN) -> Any:
    return s.client.post(
        "/alerts", json={"alerts": list(alerts)}, headers={"Authorization": f"Bearer {token}"}
    )


def test_an_alert_inside_the_window_is_a_plain_message() -> None:
    s = make()
    assert post(s, alert()).json() == {"outcomes": ["sent"]}
    assert s.sender.sent == [(NUMBER, "קריטי: ניסיונות חוזרים לנחש את קוד העצירה")]


def test_outside_the_window_a_firing_alert_uses_the_approved_template() -> None:
    s = make(window=False)
    assert post(s, alert()).json() == {"outcomes": ["template"]}
    assert s.sender.templates == [(NUMBER, "system_alert")]
    assert s.sender.template_params == [("ניסיונות חוזרים לנחש את קוד העצירה",)]


def test_outside_the_window_a_resolved_alert_is_not_worth_a_paid_message() -> None:
    s = make(window=False)
    assert post(s, alert(status="resolved")).json() == {"outcomes": ["window_closed"]}
    assert s.sender.templates == []


def test_without_a_template_nothing_goes_out_of_the_window() -> None:
    s = make(template=None, window=False)
    assert post(s, alert()).json() == {"outcomes": ["window_closed"]}


@pytest.mark.parametrize("token", ["", "wrong", TOKEN + "x"])
def test_t9_only_alertmanager_may_post(token: str) -> None:
    s = make()
    assert post(s, alert(), token=token).status_code == 401
    assert s.sender.sent == []


def test_t31_a_summary_with_a_link_is_replaced_by_a_fixed_text() -> None:
    s = make()
    post(s, alert(summary_he="היכנס ל-https://evil.example"))
    assert s.sender.sent == [(NUMBER, "קריטי: התראה ממערכת הניטור")]


def test_t24_a_storm_of_alerts_is_capped_per_hour() -> None:
    s = make()
    outcomes = post(s, *[alert()] * (MAX_MESSAGES_PER_HOUR + 3)).json()["outcomes"]
    assert outcomes.count("sent") == MAX_MESSAGES_PER_HOUR
    assert outcomes.count("capped") == 3


def test_e13_a_message_meta_refused_is_reported_as_failed() -> None:
    s = make(window=False)
    s.sender.send_template = lambda *args, **kwargs: False  # type: ignore[method-assign,assignment]
    assert post(s, alert()).json() == {"outcomes": ["send_failed"]}
