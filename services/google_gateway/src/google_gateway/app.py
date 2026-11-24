"""google-gateway's HTTP side: starting and finishing a Google connection, and a health check.

Run with `python -m google_gateway.serve`, not plain uvicorn: see serve.py for why.

The two OAuth routes are the only ones the internet can reach (the Ingress lists them):
- START_PATH: the web app's "Connect Google" button lands here with a one-time ticket the
  api issued for the logged-in user (shared.connect_ticket). The gateway trusts the ticket,
  never a user id from the browser.
- CALLBACK_PATH: Google sends the user back here with the authorization code.
Both end by redirecting the browser to the web app with an outcome code only, so the code,
the state and the ticket leave the address bar and the history at once. The web app turns
the outcome into a message; nothing from the request is echoed (T19).
"""

from typing import Protocol

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from google_gateway.connection import ConnectFlow, Outcome
from shared import connect_ticket, security, tracing
from shared.connect_ticket import ReturnTo
from shared.schema import StrictModel

START_PATH = "/oauth/google/start"
CALLBACK_PATH = "/oauth/google/callback"

_SECURITY_HEADERS = {
    # These URLs carry a ticket, a code or a state: keep them out of caches and out of the
    # Referer header of the next page (T16).
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class TicketStore(Protocol):
    def redeem(self, ticket: str) -> connect_ticket.ConnectTicket | None: ...


class RedisTickets:
    def __init__(self, redis: connect_ticket.TicketRedis) -> None:
        self._redis = redis

    def redeem(self, ticket: str) -> connect_ticket.ConnectTicket | None:
        return connect_ticket.redeem(self._redis, ticket)


class Health(StrictModel):
    status: str


def create_app(flow: ConnectFlow, tickets: TicketStore, web_app_url: str) -> FastAPI:
    # No /docs or /openapi.json: this service is not a public API.
    app = FastAPI(
        title="scheduling-agent google-gateway", docs_url=None, redoc_url=None, openapi_url=None
    )

    def back_to_app(return_to: ReturnTo, outcome: Outcome) -> RedirectResponse:
        # return_to comes from a fixed list and outcome from an enum: no open redirect.
        return RedirectResponse(
            f"{web_app_url.rstrip('/')}/{return_to}?google={outcome.value}",
            status_code=303,
            headers=_SECURITY_HEADERS,
        )

    @app.get("/healthz")
    def healthz() -> Health:
        return Health(status="ok")

    @app.get(START_PATH)
    def start(ticket: str = "") -> RedirectResponse:
        found = tickets.redeem(ticket)
        if found is None:
            # Counted, not stored: anyone can call this URL, and a row each would let them
            # fill the database (like the WhatsApp webhook's bad signatures).
            security.record("oauth_invalid_state")
            return back_to_app("onboarding", Outcome.INVALID_STATE)
        return RedirectResponse(
            flow.start(found.user_id, found.return_to), status_code=303, headers=_SECURITY_HEADERS
        )

    @app.get(CALLBACK_PATH)
    def callback(
        state: str | None = None, code: str | None = None, error: str | None = None
    ) -> RedirectResponse:
        outcome, return_to = flow.finish(state, code, error)
        return back_to_app(return_to, outcome)

    tracing.instrument_fastapi(app)
    return app
