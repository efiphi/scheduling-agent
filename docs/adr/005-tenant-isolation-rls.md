# ADR-005: Tenant isolation with PostgreSQL RLS and a DB role per service

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Several users share one database. One user seeing another user's emails, calendar or settings is the most severe failure in a multi-user system (T13). Filtering by `user_id` in every query works until one query forgets it.

## Decision

Enforce isolation in the database itself:

- Every table has a `user_id` column.
- PostgreSQL Row-Level Security is enabled (and forced) on every table, with policies that compare `user_id` to a per-transaction setting (`SET LOCAL app.user_id = ...`) set by one central data-access layer.
- `api` and `google-gateway` each connect with their own role that has grants only on the tables it needs. Neither role owns the tables or has `BYPASSRLS`. The `agent` has no role at all (ADR-011).
- Admin screens use a dedicated policy that exposes only user names and status, never user data.

## Alternatives considered

- **Filtering in application code only** — simpler, but a single missing `WHERE user_id = ...` leaks data, and nothing catches it.
- **A database or schema per tenant** — strong isolation, but heavy to operate and migrate for a handful of users.

## Consequences

- **Positive:** A bug in a query returns no rows instead of another user's rows. Role grants limit the blast radius if one service is compromised (T16, T21). Easy to demonstrate with an automated cross-tenant test.
- **Negative:** Every connection must set the user context, and connection pooling must not leak it between requests (hence `SET LOCAL` inside a transaction). Migrations run as a separate owner role. Policies add a little query overhead.

## Revisit when

Data volume makes RLS overhead measurable, or a tenant needs physical separation (e.g. compliance).

## References

- `docs/03-architecture.md` — data model, tenant isolation
- `docs/02-threat-model.md` — T13, T16
