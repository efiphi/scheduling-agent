"""FastAPI application for the api service: login, sessions and approvals (step 1.9).

Run in Docker (deploy/compose), or locally:
    uv run --env-file deploy/compose/.env uvicorn api.main:create_app --factory \\
        --host 127.0.0.1 --port 8000 --no-server-header --no-access-log

--no-server-header: callers are not told which server software to look up flaws for.
--no-access-log: the login callback URL carries an authorization code (T22).
"""

import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, SecretStr
from redis import Redis

from api.google_login import GoogleLogin, LoginError
from api.invites import (
    INVITE_LIFETIME,
    InviteCreateIn,
    InviteTokenIn,
    email_hint,
    invite_link,
    new_invite_token,
    token_hash,
    valid_email,
)
from api.sessions import LoginState, Session, SessionStore, new_token
from api.store import ApiStore, ApproveResult
from api.whatsapp import (
    Inbox,
    InboxState,
    Notifier,
    hash_stop_code,
    parse_messages,
    valid_signature,
)
from shared import connect_ticket, log, metrics, security, tracing
from shared.connect_ticket import ReturnTo
from shared.schema import StrictModel
from shared.security import record as record_security_event
from shared.streams import APPROVED_ACTIONS, STREAM_MAX_LENGTH

logger = logging.getLogger(__name__)

COOKIE = "sa_session"
CALLBACK_PATH = "/auth/google/callback"

SECURITY_HEADERS = {
    # JSON and two tiny pages: nothing to load, never framed (clickjacking), never cached.
    # base-uri and form-action do not fall back to default-src, so each is set here.
    "Content-Security-Policy": (
        "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=()",
}


class Health(StrictModel):
    status: str


class Me(BaseModel):
    email: str
    status: str
    is_admin: bool
    # Status only: the api has no access to the tokens themselves (invariant 1, migration 0008).
    google_status: Literal["connected", "expired", "revoked", "not_connected"]
    whatsapp_verified: bool
    # The browser sends this back in X-CSRF-Token on every change (T10).
    csrf_token: str


class InviteCheckOut(BaseModel):
    # Masked: whoever holds the link learns which account to use, not the full address.
    email_hint: str


class LoginUrlOut(BaseModel):
    url: str


class GoogleConnectIn(StrictModel):
    # The screen to come back to: a fixed list, so no open redirect (shared.connect_ticket).
    return_to: ReturnTo = "onboarding"


class InviteOut(BaseModel):
    invite_id: UUID
    email: str
    status: str
    expires_at: datetime
    created_at: datetime


class InviteCreatedOut(InviteOut):
    # Shown once, to the admin who made it. Only its hash is stored (migration 0007).
    link: str


class AdminUserOut(BaseModel):
    email: str
    status: str
    is_admin: bool
    whatsapp_verified: bool
    google_status: str
    created_at: datetime


class SlotOut(BaseModel):
    start: datetime
    end: datetime


class IncomingOut(BaseModel):
    """The email an action answers. Untrusted text, to show and never to act on (T19, T31)."""

    sender: str
    subject: str
    summary: str | None


class ActionOut(BaseModel):
    action_id: UUID
    kind: str
    status: str
    to: list[str]
    subject: str
    body: str
    slots: list[SlotOut]
    incoming: IncomingOut | None = None
    content_hash: str
    expires_at: datetime
    created_at: datetime


class QuestionOut(BaseModel):
    question_id: UUID
    question: str
    created_at: datetime


class ApproveIn(StrictModel):
    # The hash of exactly what the user saw. A different hash means the content changed.
    content_hash: str


class Done(BaseModel):
    status: str


class VerificationOut(BaseModel):
    # Send this code from your phone to the agent's number (inbound verification, 1b).
    code: str
    agent_number: str
    expires_in_seconds: int


class SecurityOut(BaseModel):
    agent_status: str
    whatsapp_verified: bool
    stop_code_set: bool
    # Last four digits only: the full numbers are never sent back to the browser.
    backup_numbers: list[str]


class StopCodeIn(StrictModel):
    code: str = Field(min_length=6, max_length=64)


class BackupNumbersIn(StrictModel):
    numbers: list[str] = Field(max_length=2)


@dataclass(frozen=True)
class WhatsAppDeps:
    inbox: Inbox
    state: InboxState
    app_secret: SecretStr
    verify_token: SecretStr
    agent_number: str


@dataclass(frozen=True)
class Deps:
    login: GoogleLogin
    sessions: SessionStore
    store: ApiStore
    redis: Redis
    web_app_url: str
    cookie_secure: bool
    whatsapp: WhatsAppDeps | None = None
    notifier: "Notifier | None" = None
    connect_start_url: str = "http://localhost:8001/oauth/google/start"


# Sensitive changes need a login within the last 10 minutes, not just a live session.
RECENT_LOGIN_SECONDS = 600


def _configure_logging() -> None:
    # uvicorn configures only its own loggers before it imports the app. Route them and ours
    # through one JSON handler (shared.log); our lines hold outcomes and ids only (T22).
    log.configure("api")
    tracing.configure("api")
    metrics.configure("api")


def create_app(deps: Deps | None = None) -> FastAPI:
    _configure_logging()
    if deps is None:
        from api.wiring import deps_from_env

        deps = deps_from_env()
    d = deps
    app = FastAPI(title="scheduling-agent api")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[..., Any]) -> Response:
        response: Response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def current_session(sa_session: Annotated[str | None, Cookie()] = None) -> Session:
        session = d.sessions.get(sa_session or "")
        if session is None:
            raise HTTPException(status_code=401, detail="login required")
        return session

    def csrf_checked(
        session: Annotated[Session, Depends(current_session)],
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> Session:
        # Constant-time compare: no timing hints about the token (T10).
        if not x_csrf_token or not secrets.compare_digest(x_csrf_token, session.data.csrf_token):
            raise HTTPException(status_code=403, detail="missing or wrong CSRF token")
        return session

    Auth = Annotated[Session, Depends(current_session)]
    Change = Annotated[Session, Depends(csrf_checked)]

    @app.get("/healthz")
    def healthz() -> Health:
        """Liveness only: no version or dependency details for an unauthenticated caller."""
        return Health(status="ok")

    # --- Login ------------------------------------------------------------------------

    def to_app(path: str) -> RedirectResponse:
        return RedirectResponse(f"{d.web_app_url.rstrip('/')}/{path}", status_code=303)

    @app.get("/auth/google/login")
    def login() -> RedirectResponse:
        state, verifier = new_token(), secrets.token_urlsafe(64)
        d.sessions.put_login_state(state, LoginState(code_verifier=verifier))
        return RedirectResponse(d.login.authorization_url(state, verifier), status_code=303)

    @app.post("/invites/check")
    def check_invite(body: InviteTokenIn) -> InviteCheckOut:
        """Is this invite live? The same 404 for unknown, used, revoked and expired (T14)."""
        email = d.store.invite_email(token_hash(body.token))
        if email is None:
            raise HTTPException(status_code=404, detail="invite not found")
        return InviteCheckOut(email_hint=email_hint(email))

    @app.post("/auth/google/invite")
    def login_with_invite(body: InviteTokenIn) -> LoginUrlOut:
        """Start a login that may accept this invite. The token travels in the body (T22)."""
        hashed = token_hash(body.token)
        email = d.store.invite_email(hashed)
        if email is None:
            raise HTTPException(status_code=404, detail="invite not found")
        state, verifier = new_token(), secrets.token_urlsafe(64)
        d.sessions.put_login_state(state, LoginState(code_verifier=verifier, invite_hash=hashed))
        return LoginUrlOut(url=d.login.authorization_url(state, verifier, login_hint=email))

    @app.get(CALLBACK_PATH)
    def callback(
        state: str | None = None, code: str | None = None, error: str | None = None
    ) -> Response:
        # Every refusal goes back to the web app's login screen with a short reason code;
        # nothing the attacker controls is echoed (T19).
        pending = d.sessions.take_login_state(state) if state else None
        if pending is None or error or not code:
            return to_app("login?error=failed")
        try:
            identity = d.login.exchange(code, pending.code_verifier)
        except LoginError:
            return to_app("login?error=failed")
        if not identity.email_verified:
            return to_app("login?error=not_invited")
        user_id = d.store.find_user(identity.email)
        joined = False
        if user_id is None and pending.invite_hash:
            # The invite must be live and bound to exactly this verified address (T14).
            user_id = d.store.accept_invite(pending.invite_hash, identity.email)
            joined = user_id is not None
        if user_id is None:
            # Joining is by invitation only (T14). Same answer whatever the reason.
            record_security_event("login_not_invited")
            return to_app("login?error=not_invited")
        session = d.sessions.create(user_id)
        d.store.audit(user_id, "login", {"channel": "web", "joined": joined})
        response = to_app("onboarding" if joined else "")
        response.set_cookie(
            COOKIE,
            session.session_id,
            httponly=True,  # page scripts cannot read it, so XSS cannot steal it (T19)
            secure=d.cookie_secure,
            samesite="lax",  # sent on the redirect back from Google, not on cross-site POSTs
            max_age=12 * 3600,
            path="/",
        )
        return response

    @app.post("/auth/logout")
    def logout(session: Change) -> Response:
        d.sessions.delete(session.session_id)
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.delete("/sessions")
    def logout_everywhere(session: Change) -> Done:
        count = d.sessions.delete_all(session.data.user_id)
        d.store.audit(session.data.user_id, "sessions_revoked", {"count": count})
        return Done(status="ok")

    # --- The user -----------------------------------------------------------------------

    @app.get("/me")
    def me(session: Auth) -> Me:
        user = d.store.user(session.data.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="login required")
        return Me(
            email=user.email,
            status=user.status,
            is_admin=user.is_admin,
            google_status=d.store.google_status(user.user_id),
            whatsapp_verified=d.store.whatsapp_verified(user.user_id),
            csrf_token=session.data.csrf_token,
        )

    @app.post("/integrations/google/connect")
    def connect_google(body: GoogleConnectIn, session: Change) -> LoginUrlOut:
        """A one-time ticket for google-gateway, which alone runs the consent (invariant 1)."""
        ticket = connect_ticket.issue(d.redis, session.data.user_id, body.return_to)
        return LoginUrlOut(url=f"{d.connect_start_url}?{urlencode({'ticket': ticket})}")

    # --- Actions ------------------------------------------------------------------------

    @app.get("/actions")
    def actions(
        session: Auth,
        status: Literal[
            "pending", "approved", "executed", "rejected", "expired", "failed"
        ] = "pending",
    ) -> list[ActionOut]:
        return [_out(a) for a in d.store.actions(session.data.user_id, status)]

    @app.get("/actions/{action_id}")
    def action(action_id: UUID, session: Auth) -> ActionOut:
        found = d.store.action(session.data.user_id, action_id)
        if found is None:
            raise HTTPException(status_code=404, detail="not found")
        return _out(found)

    @app.post("/actions/{action_id}/approve")
    def approve(action_id: UUID, body: ApproveIn, session: Change) -> Done:
        user = d.store.user(session.data.user_id)
        if user is None or user.status != "active":
            raise HTTPException(status_code=409, detail="the agent is paused")
        result = d.store.approve(user.user_id, action_id, body.content_hash)
        if result is not ApproveResult.APPROVED:
            # 404 for "not yours" and "missing" alike: no hint that an id exists (T13).
            code = 404 if result is ApproveResult.NOT_FOUND else 409
            raise HTTPException(status_code=code, detail=result.value)
        d.redis.xadd(
            APPROVED_ACTIONS,
            {"action_id": str(action_id), "user_id": str(user.user_id)},
            maxlen=STREAM_MAX_LENGTH,
            approximate=True,
        )
        return Done(status="approved")

    @app.post("/actions/{action_id}/reject")
    def reject(action_id: UUID, session: Change) -> Done:
        if not d.store.reject(session.data.user_id, action_id):
            raise HTTPException(status_code=404, detail="not found or not pending")
        return Done(status="rejected")

    # --- Questions from the agent -------------------------------------------------------

    @app.get("/questions")
    def questions(session: Auth) -> list[QuestionOut]:
        return [
            QuestionOut(question_id=q.question_id, question=q.question, created_at=q.created_at)
            for q in d.store.questions(session.data.user_id)
        ]

    # --- WhatsApp webhook (step 1b) -----------------------------------------------------

    add_webhook_routes(app, d)

    @app.post("/whatsapp/verify")
    def start_verification(session: Change) -> VerificationOut:
        wa = _whatsapp(d)
        code = wa.state.start_verification(session.data.user_id)
        return VerificationOut(code=code, agent_number=wa.agent_number, expires_in_seconds=600)

    # --- Security settings (ADR-014) --------------------------------------------------

    def recent_login(session: Session) -> None:
        if time.time() - session.data.authenticated_at > RECENT_LOGIN_SECONDS:
            # Sensitive: a live session is not enough, log in with Google again (T11, T28).
            raise HTTPException(status_code=401, detail="login again")

    @app.get("/security")
    def security(session: Auth) -> SecurityOut:
        user = d.store.user(session.data.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="login required")
        return SecurityOut(
            agent_status=user.status,
            whatsapp_verified=d.store.whatsapp_verified(user.user_id),
            stop_code_set=d.store.stop_code_hash(user.user_id) is not None,
            backup_numbers=["…" + n[-4:] for n in d.store.backup_numbers(user.user_id)],
        )

    @app.put("/security/stop-code")
    def set_stop_code(body: StopCodeIn, session: Change) -> Done:
        recent_login(session)
        d.store.set_stop_code_hash(session.data.user_id, hash_stop_code(body.code))
        return Done(status="ok")

    @app.put("/security/backup-numbers")
    def set_backup_numbers(body: BackupNumbersIn, session: Change) -> Done:
        recent_login(session)
        numbers = [n.strip().lstrip("+").replace(" ", "").replace("-", "") for n in body.numbers]
        if not all(n.isdigit() and 8 <= len(n) <= 15 for n in numbers):
            raise HTTPException(
                status_code=422, detail="numbers must be international, digits only"
            )
        d.store.set_backup_numbers(session.data.user_id, sorted(set(numbers)))
        return Done(status="ok")

    @app.post("/security/pause")
    def pause(session: Change) -> Done:
        """The web app's "Pause agent": the same effect as the stop code (ADR-014)."""
        d.store.pause(session.data.user_id, "web")
        return Done(status="paused")

    @app.post("/security/resume")
    def resume(session: Change) -> Done:
        recent_login(session)  # resuming needs a fresh login (invariant 12)
        d.store.resume(session.data.user_id)
        return Done(status="active")

    @app.post("/questions/{question_id}/dismiss")
    def dismiss(question_id: UUID, session: Change) -> Done:
        if not d.store.dismiss_question(session.data.user_id, question_id):
            raise HTTPException(status_code=404, detail="not found")
        return Done(status="dismissed")

    # --- Admin: invites and users (UC-A6) -----------------------------------------------

    def admin_of(session: Session) -> UUID:
        user = d.store.user(session.data.user_id)
        if user is None or not user.is_admin:
            raise HTTPException(status_code=403, detail="admins only")
        return user.user_id

    @app.post("/admin/invites", status_code=201)
    def create_invite(body: InviteCreateIn, session: Change) -> InviteCreatedOut:
        admin = admin_of(session)
        email = body.email.strip().lower()
        if not valid_email(email):
            raise HTTPException(status_code=422, detail="not an email address")
        if d.store.find_user(email) is not None:
            raise HTTPException(status_code=409, detail="already a user")
        token = new_invite_token()
        invite = d.store.create_invite(
            admin, email, token_hash(token), datetime.now(UTC) + INVITE_LIFETIME
        )
        if invite is None:  # Postgres refused: not an admin after all (migration 0007)
            raise HTTPException(status_code=403, detail="admins only")
        return InviteCreatedOut(**invite.__dict__, link=invite_link(d.web_app_url, token))

    @app.get("/admin/invites")
    def list_invites(session: Auth) -> list[InviteOut]:
        return [InviteOut(**i.__dict__) for i in d.store.invites(admin_of(session))]

    @app.delete("/admin/invites/{invite_id}")
    def revoke_invite(invite_id: UUID, session: Change) -> Done:
        if not d.store.revoke_invite(admin_of(session), invite_id):
            raise HTTPException(status_code=404, detail="not found or no longer pending")
        return Done(status="revoked")

    @app.get("/admin/users")
    def list_users(session: Auth) -> list[AdminUserOut]:
        return [AdminUserOut(**u.__dict__) for u in d.store.admin_users(admin_of(session))]

    tracing.instrument_fastapi(app)
    return app


def _whatsapp(d: Deps) -> WhatsAppDeps:
    if d.whatsapp is None:
        raise HTTPException(status_code=404, detail="not found")
    return d.whatsapp


def add_webhook_routes(app: FastAPI, d: Deps) -> None:
    """The two routes Meta calls. Also served alone by create_webhook_app."""

    @app.get("/whatsapp/webhook", include_in_schema=False)
    def webhook_handshake(
        mode: Annotated[str, Query(alias="hub.mode")] = "",
        token: Annotated[str, Query(alias="hub.verify_token")] = "",
        challenge: Annotated[str, Query(alias="hub.challenge")] = "",
    ) -> Response:
        """Meta checks the URL once, with the verify token we gave it."""
        expected = _whatsapp(d).verify_token.get_secret_value()
        if mode == "subscribe" and secrets.compare_digest(token, expected):
            return PlainTextResponse(challenge)
        raise HTTPException(status_code=403, detail="forbidden")

    @app.post("/whatsapp/webhook", include_in_schema=False)
    async def webhook(request: Request) -> Done:
        wa = _whatsapp(d)
        body = await request.body()
        if not valid_signature(wa.app_secret, body, request.headers.get("x-hub-signature-256")):
            # Not from Meta. Nothing in the body is read (T9). Counted, not stored: anyone can
            # send these, and a row each would let them fill the database.
            security.record("whatsapp_bad_signature")
            raise HTTPException(status_code=403, detail="bad signature")
        try:
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad body") from None
        for message in parse_messages(payload):
            outcome = wa.inbox.handle(message)
            logger.info("whatsapp message handled: outcome=%s", outcome)
        return Done(status="ok")


def create_webhook_app(deps: Deps | None = None) -> FastAPI:
    """Only the WhatsApp webhook, for the public tunnel (ADR-017).

    The tunnel exposes this app, on its own port, and nothing else: login, sessions and
    approvals stay reachable from this machine only. Everything Meta sends is checked here
    exactly as in the full app.
    """
    _configure_logging()
    if deps is None:
        from api.wiring import deps_from_env

        deps = deps_from_env()
    app = FastAPI(
        title="scheduling-agent whatsapp webhook", docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[..., Any]) -> Response:
        response: Response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/healthz")
    def healthz() -> Health:
        return Health(status="ok")

    add_webhook_routes(app, deps)
    tracing.instrument_fastapi(app)
    return app


def _out(action: Any) -> ActionOut:
    payload = action.payload
    return ActionOut(
        action_id=action.action_id,
        kind=action.kind,
        status=action.status,
        to=list(payload.get("to", [])),
        subject=str(payload.get("subject", "")),
        body=str(payload.get("body", "")),
        slots=[SlotOut(**slot) for slot in payload.get("slots", [])],
        incoming=IncomingOut(**payload["incoming"]) if payload.get("incoming") else None,
        content_hash=action.content_hash,
        expires_at=action.expires_at,
        created_at=action.created_at,
    )
