# ADR-006: Four services, split by key ownership

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The component that reads untrusted email is exactly the component an attacker will try to manipulate with prompt injection (T1–T7). If that same component also holds the Google tokens, a successful injection can send email or change the calendar. The split into services should follow that risk, not a wish for microservices.

## Decision

Four services, each defined by which secret it holds and what it is allowed to reach:

| Service | Holds | Can reach |
|---|---|---|
| `api` | Session keys, Meta (WhatsApp) token, stop-code pepper | PostgreSQL, Redis, Meta |
| `google-gateway` | Google OAuth tokens, token encryption key | PostgreSQL, Redis, Google |
| `agent` | LLM provider key only | Redis, LLM provider |
| `web` | Nothing (static files) | `api` only, from the browser |

The agent proposes; the gateway checks with a deterministic policy guard and executes only with a valid approval record.

## Alternatives considered

- **One service** — far simpler to build and deploy, but prompt injection in the agent code path would run with full access to Gmail and Calendar. Isolation inside one process cannot be enforced by the network or by the operating system.
- **Finer microservices** (separate poller, separate guard, separate notifier) — more boundaries without a new secret to protect, so more operational cost and no extra security.

## Consequences

- **Positive:** A fully compromised agent still cannot send email, touch the calendar or read the database (T1, T16). Network policies can enforce the boundaries in Kubernetes (T21). Each boundary is a clear, defendable interview answer.
- **Negative:** More moving parts: inter-service messages need schemas (`packages/shared`), and debugging spans services, which is why tracing comes in Layer 3. Local development needs Docker Compose from the start.

## Revisit when

The open question about a separate "reader" LLM is decided — a second model might be a fifth component — or a new secret appears that does not fit an existing owner.

## References

- `docs/03-architecture.md` — goal and principles (principle 1), components
- `docs/02-threat-model.md` — T1–T7, T16, T21, defense principle 5 (isolation)
