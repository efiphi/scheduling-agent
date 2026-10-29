# ADR-010: Two OAuth flows; Google tokens land only in `google-gateway`

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Google is used for two unrelated things: signing in to the web app, and giving the system access to the user's Gmail and Calendar. Invariant 1 says only `google-gateway` may hold Google tokens. If both happen in one OAuth flow handled by `api`, the authorization code — and the refresh token it is exchanged for — passes through `api`, which also faces the internet and handles webhooks (T16).

## Decision

Two separate OAuth flows:

1. **Login** — handled by `api` with OpenID Connect and identity scopes only. No refresh token is requested or stored; `api` keeps only its own session cookie.
2. **Connect Gmail and Calendar** — the web app calls `POST /integrations/google/connect`; `api` returns a redirect URL that `google-gateway` built (with a random, single-use `state` kept in Redis for 10 minutes and bound to the logged-in user, plus PKCE). Google redirects back to a callback on `google-gateway`, which exchanges the code, checks that the granted scopes are exactly the ones below and that the Google account is the user's own, encrypts the refresh token with its own key (ADR-016) and stores it. `api` never sees the code or the token.

### Scopes

| Scope | Flow | Why it is needed |
|---|---|---|
| `openid` | Login | Identify the user (OIDC). |
| `email` | Login | Match the login to the invited email address (T14). |
| `https://www.googleapis.com/auth/gmail.readonly` | Connect | Read new messages and threads through the History API (ADR-003). Cannot modify or delete mail. |
| `https://www.googleapis.com/auth/gmail.send` | Connect | Send approved replies in the existing thread. Cannot read, modify or delete mail. |
| `https://www.googleapis.com/auth/calendar.events.owned` | Connect | Read events to compute free/busy ourselves, and create, update or cancel events with a Meet link — only on calendars the user owns, not on other calendars shared with them. |

Not requested: `https://mail.google.com/` (full access, includes permanent delete), `gmail.modify` (can trash messages), `calendar` (can delete whole calendars and change sharing), `profile`.

**Implementation of the login flow (step 1.9):** `api` builds the consent URL itself (`openid email`, PKCE, a single-use `state` in Redis) and exchanges the code with one HTTPS call to Google's token endpoint. It uses `google-auth` only to verify the id_token's signature, issuer, audience and expiry. It has no OAuth client library and no Google API client, and CI checks that the api image contains neither. Only an existing user's verified email gets a session (invitations come later; until then users are created by the owner, `python -m db.dev create-user`).

## Alternatives considered

- **One flow with all scopes, handled by `api`** — one consent screen, but `api` would see the authorization code and could exchange it for tokens, breaking invariant 1.
- **`api` receives the callback and forwards the code to the gateway without storing it** — keeps tokens out of `api`'s storage, but `api` still handles material a token is minted from, and a bug or log line in `api` could leak it.
- **`calendar.events` instead of `calendar.events.owned`** — covers every calendar the user can access, including colleagues' shared calendars. More than we need (T18).
- **The `freeBusy.query` endpoint** — it does not accept the events scopes, so it would need an extra scope. It also counts every invite as busy, while T26 requires that invites from unknown senders not count as busy until the user accepts them. Reading events and computing free/busy in the gateway solves both.

## Consequences

- **Positive:** `api`, the most exposed service, never handles Google credentials. The Gmail scopes together cannot delete or modify mail. Every scope is listed with a reason, as invariant 6 requires.
- **Negative:** The user sees two Google consent screens (login, then connect). `google-gateway` needs a public route for the callback — its only inbound path from the internet, which the network policy must allow and nothing else. `calendar.events.owned` still allows deleting events on owned calendars, so cancellation goes through the policy guard and needs approval. `gmail.readonly` is a restricted scope: fine while the OAuth app stays in testing mode, but leaving testing mode would require Google's paid security assessment. In testing mode refresh tokens expire after 7 days (E13).

## Revisit when

The app leaves Google's testing mode, a feature needs a scope not listed here, or Google ships a narrower Gmail scope that still allows reading thread content. `calendar.events.owned` is the starting point; expanding to `calendar.events` is expected once a feature needs events on calendars the user does not own (e.g. shared team calendars), and will be recorded in a new ADR.

## References

- `docs/03-architecture.md` — security decisions in the architecture (OAuth, scopes, network separation)
- `docs/04-web-app.md` — users and login, onboarding
- `docs/02-threat-model.md` — T14, T16, T18, T26, E13
- Google Calendar API scopes: https://developers.google.com/workspace/calendar/api/auth
