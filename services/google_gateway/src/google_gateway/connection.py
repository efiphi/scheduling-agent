"""Connecting a user's Google account (UC-A*, ADR-010): start, then complete on callback.

The checks in `complete`, in order, and what each one stops:
1. state: known, unexpired, unused (oauth_state.py) - login CSRF and replay.
2. Google's answer: the user may decline consent; that is not an attack.
3. code exchange with PKCE - an intercepted code is useless without the verifier.
4. scopes: exactly the five we ask for, no fewer and no more (invariant 6, T18).
5. account: the Google account must be the user's own verified email, so nobody connects
   a different mailbox to this user, by mistake or on purpose (T16).
6. a refresh token must be present, or the agent cannot work while the user is away.
Only then is the refresh token encrypted (ADR-016) and stored. The access token and the
authorization code are dropped. Nothing secret is logged: outcomes and ids only (T22).
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from google_gateway.credentials_store import CredentialRepository
from google_gateway.google_oauth import SCOPES, GoogleGrant, GoogleOAuthClient
from google_gateway.oauth_state import (
    PendingConnect,
    StateStore,
    new_code_verifier,
    new_state,
)
from google_gateway.token_crypto import TokenCipher

logger = logging.getLogger(__name__)


class Outcome(StrEnum):
    CONNECTED = "connected"
    DECLINED = "declined"
    INVALID_STATE = "invalid_state"
    EXCHANGE_FAILED = "exchange_failed"
    WRONG_SCOPES = "wrong_scopes"
    WRONG_ACCOUNT = "wrong_account"
    NO_REFRESH_TOKEN = "no_refresh_token"  # noqa: S105 - an outcome name, not a secret
    UNKNOWN_USER = "unknown_user"


@dataclass(frozen=True)
class ConnectFlow:
    states: StateStore
    google: GoogleOAuthClient
    repo: CredentialRepository
    cipher: TokenCipher

    def start(self, user_id: UUID) -> str:
        """Return the Google consent URL for this user. It works once, for 10 minutes."""
        state, verifier = new_state(), new_code_verifier()
        self.states.put(state, PendingConnect(user_id=user_id, code_verifier=verifier))
        return self.google.authorization_url(state, verifier)

    def complete(self, state: str | None, code: str | None, error: str | None) -> Outcome:
        pending = self.states.take(state) if state else None
        if pending is None:
            self.repo.security_event(None, "oauth_invalid_state", {})
            return self._done(Outcome.INVALID_STATE, None)
        user_id = pending.user_id

        if error is not None or not code:
            # Google sends error=access_denied when the user clicks Cancel.
            self.repo.audit(user_id, "google_connect_declined", {})
            return self._done(Outcome.DECLINED, user_id)

        try:
            grant = self.google.exchange(code, pending.code_verifier)
        except Exception as exc:
            # Only the exception type: library messages can echo parts of the request.
            self.repo.security_event(
                user_id, "oauth_exchange_failed", {"error": type(exc).__name__}
            )
            return self._done(Outcome.EXCHANGE_FAILED, user_id)

        return self._check_and_store(user_id, grant)

    def _check_and_store(self, user_id: UUID, grant: GoogleGrant) -> Outcome:
        if grant.scopes != SCOPES:
            details = {
                "missing": sorted(SCOPES - grant.scopes),
                "unexpected": sorted(grant.scopes - SCOPES),
            }
            self.repo.audit(user_id, "google_connect_rejected_scopes", details)
            return self._done(Outcome.WRONG_SCOPES, user_id)

        email = self.repo.user_email(user_id)
        if email is None:
            return self._done(Outcome.UNKNOWN_USER, user_id)
        if not (grant.email_verified and grant.email and grant.email.lower() == email.lower()):
            # No email addresses in the event: the user id is enough to investigate.
            self.repo.security_event(user_id, "google_account_mismatch", {})
            return self._done(Outcome.WRONG_ACCOUNT, user_id)

        if not grant.refresh_token:
            self.repo.audit(user_id, "google_connect_no_refresh_token", {})
            return self._done(Outcome.NO_REFRESH_TOKEN, user_id)

        encrypted = self.cipher.encrypt(grant.refresh_token, user_id)
        self.repo.save_credentials(user_id, encrypted, sorted(grant.scopes))
        return self._done(Outcome.CONNECTED, user_id)

    @staticmethod
    def _done(outcome: Outcome, user_id: UUID | None) -> Outcome:
        logger.info("google connect finished: outcome=%s user_id=%s", outcome, user_id)
        return outcome
