"""google-gateway's HTTP side. For now: the OAuth callback and a health check.

Run with `python -m google_gateway.serve`, not plain uvicorn: see serve.py for why.
"""

from html import escape

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from google_gateway.connection import ConnectFlow, Outcome
from shared.schema import StrictModel

CALLBACK_PATH = "/oauth/google/callback"
RESULT_PATH = "/oauth/google/result"

# The result page is the only UI this service has. Hebrew, like the web app (MVP).
_MESSAGES: dict[Outcome, str] = {
    Outcome.CONNECTED: "חשבון Google חובר בהצלחה. אפשר לסגור את החלון.",
    Outcome.DECLINED: "החיבור בוטל. לא נשמר דבר.",
    Outcome.INVALID_STATE: "הקישור לא תקף, פג תוקפו או כבר נוצל. התחילו את החיבור מחדש.",
    Outcome.EXCHANGE_FAILED: "Google לא אישר את החיבור. התחילו מחדש.",
    Outcome.WRONG_SCOPES: "כדי שהסוכן יעבוד צריך לאשר את כל ההרשאות. התחילו מחדש וסמנו את כולן.",
    Outcome.WRONG_ACCOUNT: "זה לא החשבון שרשום אצלנו. התחברו עם החשבון הנכון.",
    Outcome.NO_REFRESH_TOKEN: "Google לא החזיר הרשאה לטווח ארוך. התחילו מחדש.",
    Outcome.UNKNOWN_USER: "המשתמש לא נמצא.",
}
_UNKNOWN = "משהו השתבש. התחילו את החיבור מחדש."

_SECURITY_HEADERS = {
    # The callback URL carries the authorization code: keep it out of caches and out of
    # the Referer header of anything this page might load (T16).
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    # The page loads nothing: no scripts, no images, no frames, inline styles only.
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
}


class Health(StrictModel):
    status: str


def create_app(flow: ConnectFlow) -> FastAPI:
    # No /docs or /openapi.json: this service is not a public API.
    app = FastAPI(
        title="scheduling-agent google-gateway", docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.get("/healthz")
    def healthz() -> Health:
        return Health(status="ok")

    @app.get(CALLBACK_PATH)
    def callback(
        state: str | None = None, code: str | None = None, error: str | None = None
    ) -> Response:
        outcome = flow.complete(state, code, error)
        # Redirect so the code and state leave the address bar and the browser history.
        return RedirectResponse(
            f"{RESULT_PATH}?outcome={outcome.value}", status_code=303, headers=_SECURITY_HEADERS
        )

    @app.get(RESULT_PATH)
    def result(outcome: str = "") -> HTMLResponse:
        try:
            known: Outcome | None = Outcome(outcome)
        except ValueError:
            known = None
        message = _MESSAGES[known] if known else _UNKNOWN
        status = 200 if known in (Outcome.CONNECTED, Outcome.DECLINED) else 400
        return HTMLResponse(_page(message), status_code=status, headers=_SECURITY_HEADERS)

    return app


def _page(message: str) -> str:
    return (
        '<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
        "<title>חיבור Google</title></head>"
        '<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;'
        'padding:0 1rem;line-height:1.6">'
        f"<p>{escape(message)}</p></body></html>"
    )
