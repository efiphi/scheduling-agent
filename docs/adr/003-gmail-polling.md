# ADR-003: Poll Gmail every minute in the MVP

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

`google-gateway` must notice new emails. Gmail offers push notifications through Google Cloud Pub/Sub, or the client can poll. Meeting coordination is not real-time: a reply within a few minutes is fine. The MVP runs locally, behind a Cloudflare Tunnel, on a budget of about $30/month.

## Decision

`google-gateway` polls Gmail once a minute using the History API (`users.history.list` from the last stored `historyId`), so each poll fetches only what changed since the previous one.

## Alternatives considered

- **Push via Pub/Sub (`users.watch`)** — near-instant, but needs a Google Cloud Pub/Sub topic, a public HTTPS endpoint that receives the pushes (another inbound surface to authenticate), and renewing the watch every 7 days. More moving parts for a latency gain users will not notice.

## Consequences

- **Positive:** No public endpoint and no extra Google Cloud service. Simple to test and replay. The History API keeps each poll cheap.
- **Negative:** Up to a minute of delay. A poll runs even when nothing arrived, which costs API quota but stays far below Gmail's limits for a few users. If a stored `historyId` expires (after long downtime), the gateway must fall back to a full sync of recent messages.

## Revisit when

There are enough users that per-minute polling approaches Gmail API quotas, or a use case needs sub-minute reaction.

## References

- `docs/03-architecture.md` — main flows (incoming email), scheduled jobs
- Gmail API: `users.history.list`, `users.watch`
