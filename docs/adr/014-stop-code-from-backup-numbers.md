# ADR-014: Emergency stop only from registered backup numbers, plus a web pause

- **Status:** Accepted (supersedes [ADR-013](013-stop-code-hmac.md))
- **Date:** 2026-10-25

## Context

ADR-013 assumed the stop code could be sent from **any** phone (UC-W8 as first written). That forces the system to inspect messages from unknown numbers — the only place where it processes input from strangers — and to find the owner from the code alone, which is why ADR-013 needed an HMAC with a pepper and a unique index. Every unknown number in the world can attempt guesses (T28).

The owner's view: a user should register in advance the phone(s) a stop may come from. The threat is still a lost or stolen phone (T11), so the stop must work without the user's main phone.

## Decision

- At onboarding each user registers **one or two backup WhatsApp numbers** (for example a partner's phone) in addition to their own verified number, and a stop code.
- A stop is accepted only when **both** hold: the sender is the user's verified number or one of their backup numbers, **and** the message is the user's stop code. Something you have (a registered phone) plus something you know (the code).
- Messages from numbers that are neither verified nor a backup are dropped before any processing, with no reply and only a `security_events` entry (T8).
- The code is stored as an **argon2id** hash per user. The sender's number identifies the candidate user(s), so only their hash is checked — a slow, salted hash is affordable again, and no pepper is needed. (A backup number may serve more than one user, e.g. two partners; the code is checked against each of those few users.)
- The web app gets a **"Pause agent"** button on the security screen, available after normal login from any browser. It has the same effect as the stop code. Resuming still requires re-authentication with Google.
- Adding or changing backup numbers is a sensitive-settings change: it needs extra verification (invariant 11) and re-authentication in the web app.
- Rate limits stay: per sender and per user, with a notification to the user on every failed attempt.

## Alternatives considered

- **Any phone + code (ADR-013)** — most available in an emergency, but keeps a stranger-facing input path and needs HMAC with a pepper to find the owner from the code alone.
- **Backup numbers without a code** — simplest, but whoever holds the backup phone could pause the agent at will. Pausing is safe (nothing is executed), but it is still a denial of service and an annoyance.

## Consequences

- **Positive:** Unknown numbers are never processed, which makes T8 a simple rule and nearly removes the guessing surface of T28. Standard password hashing replaces the pepper scheme, so one fewer secret to manage: the "stop-code pepper" listed for `api` in ADR-006 and among the cluster secrets in ADR-008 is no longer needed. The web pause covers the case where no registered phone is at hand.
- **Negative:** In an emergency the user needs either a registered backup phone or a browser where they can log in to Google. If the attacker also controls the backup phone and knows the code, they can pause the agent — the worst outcome is a pause, which cannot execute anything. Onboarding gets one more step, and each backup number must be verified (a one-time code sent to it) so a typo does not register a stranger's number.

## Revisit when

Users report they could not stop the agent in a real emergency, or stop codes need to work for users who have no second phone to register.

## References

- [ADR-013](013-stop-code-hmac.md) — superseded
- `docs/01-use-cases.md` — UC-W8, settings
- `docs/02-threat-model.md` — T8, T11, T28
- `docs/03-architecture.md` — main flows (WhatsApp command, emergency stop), data model (`users`)
- `docs/04-web-app.md` — onboarding, security screen, API endpoints
