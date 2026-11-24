"""The callback and result endpoints (app.py)."""

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from gateway_fakes import CODE, USER_EMAIL, FakeGoogle, FakeRepo, FakeStates
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from google_gateway.app import CALLBACK_PATH, START_PATH, create_app
from google_gateway.connection import ConnectFlow
from google_gateway.token_crypto import KEY_BYTES, TokenCipher
from shared import connect_ticket, tracing

APP = "https://agent.example/"


class Tickets:
    """The api's side of shared.connect_ticket, in memory."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def set(self, name: str, value: str, ex: int, nx: bool) -> bool:
        self.items[name] = value
        return True

    def getdel(self, name: str) -> str | None:
        return self.items.pop(name, None)

    def redeem(self, ticket: str) -> connect_ticket.ConnectTicket | None:
        return connect_ticket.redeem(self, ticket)


@pytest.fixture
def flow() -> ConnectFlow:
    user_id = uuid4()
    return ConnectFlow(
        states=FakeStates(),
        google=FakeGoogle(),
        repo=FakeRepo(emails={user_id: USER_EMAIL}),
        cipher=TokenCipher({1: bytes([7]) * KEY_BYTES}),
    )


@pytest.fixture
def tickets() -> Tickets:
    return Tickets()


def client_for(flow: ConnectFlow, tickets: Tickets) -> TestClient:
    return TestClient(create_app(flow, tickets, APP))


def start(flow: ConnectFlow) -> str:
    user_id = next(iter(flow.repo.emails))  # type: ignore[attr-defined]
    return parse_qs(urlparse(flow.start(user_id)).query)["state"][0]


# --- Starting from the web app ----------------------------------------------------------------


def test_t16_a_ticket_from_the_api_starts_the_consent_for_its_user(
    flow: ConnectFlow, tickets: Tickets
) -> None:
    user_id = next(iter(flow.repo.emails))  # type: ignore[attr-defined]
    ticket = connect_ticket.issue(tickets, user_id, "settings/security")
    response = client_for(flow, tickets).get(
        START_PATH, params={"ticket": ticket}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("https://accounts.example/")
    (pending,) = flow.states.items.values()  # type: ignore[attr-defined]
    assert (pending.user_id, pending.return_to) == (user_id, "settings/security")
    # Used once: the same ticket cannot start a second consent.
    again = client_for(flow, tickets).get(
        START_PATH, params={"ticket": ticket}, follow_redirects=False
    )
    assert again.headers["location"] == f"{APP}onboarding?google=invalid_state"


@pytest.mark.parametrize("ticket", ["", "forged", "x" * 43])
def test_t16_without_a_valid_ticket_no_consent_starts(
    flow: ConnectFlow, tickets: Tickets, ticket: str
) -> None:
    response = client_for(flow, tickets).get(
        START_PATH, params={"ticket": ticket}, follow_redirects=False
    )
    assert response.headers["location"] == f"{APP}onboarding?google=invalid_state"
    assert flow.states.items == {}  # type: ignore[attr-defined]
    assert flow.repo.security_events == []  # type: ignore[attr-defined]  # counted, not stored


# --- Back from Google -------------------------------------------------------------------------


def test_callback_returns_to_the_app_and_drops_the_code_from_the_url(
    flow: ConnectFlow, tickets: Tickets
) -> None:
    state = start(flow)
    response = client_for(flow, tickets).get(
        CALLBACK_PATH, params={"state": state, "code": CODE}, follow_redirects=False
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location == f"{APP}onboarding?google=connected"
    assert CODE not in location and state not in location
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_callback_returns_to_the_screen_the_user_started_from(
    flow: ConnectFlow, tickets: Tickets
) -> None:
    user_id = next(iter(flow.repo.emails))  # type: ignore[attr-defined]
    state = parse_qs(urlparse(flow.start(user_id, "settings/security")).query)["state"][0]
    response = client_for(flow, tickets).get(
        CALLBACK_PATH, params={"state": state, "code": CODE}, follow_redirects=False
    )
    assert response.headers["location"] == f"{APP}settings/security?google=connected"


def test_forged_callback_returns_an_outcome_code_only(flow: ConnectFlow, tickets: Tickets) -> None:
    response = client_for(flow, tickets).get(
        CALLBACK_PATH,
        params={"state": "<script>alert(1)</script>", "code": CODE},
        follow_redirects=False,
    )
    assert response.headers["location"] == f"{APP}onboarding?google=invalid_state"


def test_no_api_docs_are_exposed(flow: ConnectFlow, tickets: Tickets) -> None:
    client = client_for(flow, tickets)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


# --- Tracing (Layer 3, T16, T22) -------------------------------------------------------------

_SPANS = InMemorySpanExporter()


@pytest.fixture
def spans() -> InMemorySpanExporter:
    provider = tracing.configure("google-gateway")
    if not getattr(provider, "_gateway_test_exporter", False):
        provider.add_span_processor(SimpleSpanProcessor(_SPANS))
        provider._gateway_test_exporter = True  # type: ignore[attr-defined]
    _SPANS.clear()
    return _SPANS


def test_t16_the_oauth_routes_are_never_traced(
    flow: ConnectFlow, tickets: Tickets, spans: InMemorySpanExporter
) -> None:
    # Their query strings hold the ticket, the code and the state; a span would record them.
    client = client_for(flow, tickets)
    client.get(CALLBACK_PATH, params={"state": start(flow), "code": CODE}, follow_redirects=False)
    client.get(START_PATH, params={"ticket": "t" * 43}, follow_redirects=False)
    recorded = " ".join(str(s.attributes) for s in spans.get_finished_spans())
    assert CODE not in recorded and "t" * 43 not in recorded
    assert not [
        s
        for s in spans.get_finished_spans()
        if CALLBACK_PATH in str(s.attributes) or START_PATH in str(s.attributes)
    ]


def test_a_traceparent_header_from_outside_is_ignored(
    flow: ConnectFlow, tickets: Tickets, spans: InMemorySpanExporter
) -> None:
    outside = "ab" * 16
    client = client_for(flow, tickets)
    client.get("/docs", headers={"traceparent": f"00-{outside}-{'cd' * 8}-01"})
    finished = spans.get_finished_spans()
    assert finished  # an ordinary route is traced...
    assert all(f"{s.context.trace_id:032x}" != outside for s in finished)  # ...in its own trace
    assert all(s.parent is None or s.parent.trace_id != int(outside, 16) for s in finished)
