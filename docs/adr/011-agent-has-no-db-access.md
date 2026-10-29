# ADR-011: The agent has no database access

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The agent is the only service that reads untrusted content and passes it to an LLM, so it is the most likely to be manipulated (T1–T7). It still needs context: the user's working hours and other relevant settings, the contacts in the thread, and free/busy for a time range. Giving it a read-only database role would be simple, but even read access to the database is enough to leak another user's data if RLS were ever misconfigured (T13), or to exfiltrate data through a manipulated reply.

## Decision

The agent has no database role and no database network access.

- Each task the gateway (or `api`, for WhatsApp commands) puts on the Redis stream carries the minimal context the agent needs: relevant settings and the contacts already in the thread.
- Free/busy is a request/reply over Redis: the agent writes a request with a correlation ID to a stream the gateway consumes, and waits for the reply on a key named after its request. The reply contains busy intervals only — no titles, attendees or descriptions (invariant 5, E6).
- LangGraph checkpoints, if ever needed, are stored in Redis (deferred for now, ADR-002).
- **Implementation (step 1.6b):** the agent writes `FreeBusyRequest` to the `gateway:free-busy-requests` stream and waits (BLPOP) on a reply key named after the request id, so only the agent that asked gets the answer, even with several replicas. In Docker Compose the agent sits on a network that reaches Redis only: it cannot even resolve the database's hostname. Its image contains no database driver and no Google library (checked in CI).

## Alternatives considered

- **Read-only DB role with RLS** — less plumbing, but a compromised agent could read anything that role and its RLS policies allow, and the network policy would have to allow the database.
- **Agent calls the gateway over HTTP** — a direct API is easy to reason about, but it opens another network path to the service that holds the Google tokens. Redis is already the agent's only allowed path.

## Consequences

- **Positive:** A fully compromised agent can only see what was put in its task and can only write to its own Redis streams. The context it receives is exactly what the threat model allows it to see, which makes T1 and E6 easy to test. The network policy for the agent stays short: Redis and the LLM provider.
- **Negative:** The context schema must be defined and versioned in `packages/shared`. Free/busy needs a timeout and a clear error path when the gateway does not answer (E13). Adding a new piece of context means changing the producer, not just a query.

## Revisit when

The agent needs context that is too large or too dynamic to ship with each task (e.g. long-term memory, which is out of the MVP's scope).

## References

- `docs/03-architecture.md` — overview, components (Agent), main flows, tenant isolation
- `docs/02-threat-model.md` — T1–T7, T13, E6, E13
