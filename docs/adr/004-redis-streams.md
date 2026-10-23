# ADR-004: Redis Streams for queues, locks and rate limits

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The services hand work to each other asynchronously (gateway → agent → gateway), and the agent needs a request/reply channel for free/busy because it has no other network access (ADR-011). Separately, we need a short-lived lock on a time slot right before execution to prevent double booking (E1), and rate limits on webhooks, stop-code attempts and per-sender email processing (T24, T28).

## Decision

Use Redis for all three: Redis Streams with consumer groups for queues and request/reply, `SET NX` with an expiry for slot locks, and counters with expiry for rate limits. LangGraph checkpoints are also stored in Redis.

## Alternatives considered

- **RabbitMQ** — mature queues with acknowledgements, but does not cover locks or rate limits, so we would still run Redis.
- **NATS / JetStream** — light and fast, the same gap.
- **PostgreSQL as a queue (`SKIP LOCKED`)** — one fewer component, but the agent has no database access by design, so it could not consume from it.

## Consequences

- **Positive:** One component covers four needs. Consumer groups give at-least-once delivery and a pending list for retries. Simple to run locally in Docker Compose.
- **Negative:** At-least-once delivery means a message can be processed twice, so every handler must be idempotent (E8). Redis holds queues in memory; persistence (AOF) must be enabled so a restart does not drop pending work. Redis becomes a shared dependency: the agent's network policy allows only Redis and the LLM provider, so access must be limited per service with Redis ACLs.

## Revisit when

Queue volume or durability needs exceed what a single Redis instance gives, or we need cross-region delivery.

## References

- `docs/03-architecture.md` — components table (Redis)
- `docs/02-threat-model.md` — E1, E8, T24, T28
