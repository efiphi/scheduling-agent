# ADR-013: Emergency stop code stored as an HMAC with a pepper

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

If a user's phone is lost or stolen (T11), they send a secret stop code from any other phone to the agent's WhatsApp number. The message can come from an unknown number, so the system must find which user the code belongs to from the code alone. Codes must not be recoverable from a database leak, guessing must be rate-limited (T28), and an unknown number must not learn whether a code was valid (T8).

Storing the code with a slow password hash (argon2 or bcrypt, each with a random salt) protects it well, but then finding the owner means hashing the incoming message once per user — slow, and it gets slower as users are added.

## Decision

Store `HMAC-SHA256(pepper, normalized_code)` in `users.stop_code_hmac` with a unique index.

- The pepper is a secret held only by `api` (in Kubernetes, a Sealed Secret — ADR-008), never in the database.
- On every inbound WhatsApp message, before any other processing, `api` computes the HMAC of the normalized text and looks it up through the index. A match pauses that user and cancels their pending actions.
- Codes are long (at least 12 characters) and chosen at onboarding. The unique index also rejects a code another user already uses.
- Attempts are rate-limited per sending number and globally. A miss from an unknown number gets no reply. Failed attempts are logged to `security_events` and the user is notified.

## Alternatives considered

- **Slow hash (argon2) per user** — the standard for passwords, but lookup requires one slow hash per user per inbound message, which does not scale and is itself a denial-of-service lever.
- **Code that includes a user identifier (e.g. `efi-XXXX`)** — allows a single argon2 check, but reveals part of the secret structure, and a user in an emergency has one more thing to remember.
- **Plain SHA-256** — fast lookup, but anyone with a database dump could brute-force short codes offline.

## Consequences

- **Positive:** Constant-time lookup from any number. A database leak alone is not enough to brute-force codes, because the pepper is elsewhere. No information leaks to unknown numbers.
- **Negative:** If the pepper and the database leak together, protection relies on code length, not on a slow hash — hence the minimum length. Rotating the pepper requires every user to set a new code. Normalization (case, whitespace, Hebrew/English digits) must be defined once and tested.

## Revisit when

A key management service becomes available (then the HMAC can run there and the pepper never leaves it), or users ask for short codes.

## References

- `docs/03-architecture.md` — main flows (emergency stop), data model (`users`)
- `docs/02-threat-model.md` — T8, T11, T28
- `docs/01-use-cases.md` — UC-W8
