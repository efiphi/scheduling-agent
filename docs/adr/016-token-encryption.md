# ADR-016: Google refresh tokens encrypted with AES-256-GCM, bound to their user

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

`google_credentials` holds each user's Google refresh token — the most sensitive asset in the system: whoever has it can read and send that user's email (T16). Database grants keep every service except `google-gateway` away from the table (migration 0001), and Row-Level Security keeps the gateway to one user per transaction (migration 0002). Neither helps if the database itself leaks: a backup, a dump, a stolen volume.

Two further risks: a bug or a direct database write could move one user's token into another user's row (T13), and tokens or keys could end up in logs or tracebacks (T22).

## Decision

Encrypt the refresh token in `google-gateway` before it reaches the database, with **AES-256-GCM** from the `cryptography` library:

- **Authenticated encryption.** Any change to the stored bytes fails decryption rather than yielding a different token.
- **A fresh random 96-bit nonce per encryption**, stored in front of the ciphertext.
- **Bound to its user.** The user id (with a purpose prefix) is authenticated associated data. A token copied into another user's row does not decrypt.
- **Keys outside the database.** They come from `TOKEN_ENCRYPTION_KEYS`, visible to `google-gateway` only: the git-ignored `.env` locally, a Sealed Secret in Kubernetes (ADR-008).
- **Versioned keys.** `1:<base64>,2:<base64>`; new tokens use the highest version, and `key_version` is stored with each token, so a key can be rotated without breaking existing tokens.
- **Only the refresh token is stored.** Access tokens live for an hour, in memory only.
- **Nothing secret is printed.** The cipher's representation lists key versions only; configuration errors do not echo key material.

## Alternatives considered

- **Database-level encryption (pgcrypto)** — the key would have to be sent to the database with each query, where it could appear in logs or `pg_stat_activity`.
- **Disk or volume encryption only** — protects a stolen disk, not a dump or a backup read through the database.
- **A cloud key management service with envelope encryption** — the strongest option: the key never leaves the service. It needs a cloud account and costs money, and the system runs locally until Layer 6. The versioned design here makes a later move straightforward.
- **Fernet** (also in `cryptography`) — simpler, but has no associated data, so it cannot bind a token to its user.

## Consequences

- **Positive:** A database leak alone exposes no usable token. Tokens cannot be swapped between users. Rotation is possible without downtime.
- **Negative:** Losing the key means every user reconnects Google. The key must be backed up apart from the database (with the Sealed Secrets key, ADR-008). A process that holds both the key and database access — `google-gateway` — can still decrypt, so the service boundary (ADR-006) and network policy remain essential.

## Revisit when

The system runs long-term in the cloud (move to a key management service), or a second secret of the same kind needs encrypting.

## References

- ADR-006, ADR-008, ADR-010
- `docs/02-threat-model.md` — T13, T16, T22
- `services/google_gateway/src/google_gateway/token_crypto.py`
