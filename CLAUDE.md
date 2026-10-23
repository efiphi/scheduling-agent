# Scheduling Agent

A secure, multi-user AI agent that reads a user's Gmail, detects meeting requests, proposes slots from Google Calendar, and acts only after the user approves. Users talk to their agent over WhatsApp and manage everything in a web app.

This is a public portfolio project that should also work in daily use. It targets three role tracks: AI Engineering (the agent), AI Security (threat model + red team), and DevOps/Platform (Kubernetes, CI/CD, observability). The security design is the differentiator — treat it as a first-class feature, not an add-on.

## Source of truth

The design docs live in `docs/` and are written in Hebrew. Read the relevant doc before working on any area.

- `docs/01-use-cases.md` — what the system does (use cases UC-M*, UC-W*, UC-C*, UC-A*, settings, decisions)
- `docs/02-threat-model.md` — attacks (T1–T30) and failures (E1–E13), with mitigations and priorities
- `docs/03-architecture.md` — components, flows, data model, CI/CD, build layers, ADR list
- `docs/04-web-app.md` — screens, states, web security, API endpoints

Threat and failure IDs (e.g. T5, E1) are referenced everywhere. Use them in code comments, tests and PR descriptions when a change addresses one.

If a doc and the code disagree, stop and ask which one is right. If a decision changes behavior, update the doc in the same PR.

## Security invariants — never violate

1. **Only `google-gateway` holds Google tokens or calls Google APIs.** The `agent` service never sees tokens and cannot send email or modify the calendar. (T1, T16)
2. **External content is data, never instructions.** Email bodies, forwarded messages, calendar invites and other agents' replies are marked untrusted and can never trigger a state-changing tool or create an approval. (T1–T7, T15)
3. **Every outbound action passes the deterministic policy guard** in `google-gateway` before execution: recipients already in the thread (new recipients need explicit approval), slot still free under a Redis lock, no content beyond scheduling, anomaly check. (T3, T5, E1)
4. **Approvals are records, not text.** An approval is a single-use DB record bound to the user and to the hash of the exact action. Changed content invalidates it. Approvals expire at the user's configured end of workday. (T3, T10, E7)
5. **While handling external content, the agent gets free/busy only** — no event titles, attendees or descriptions. (T1, E6)
6. **Minimal OAuth scopes, no delete permission.** Document every scope and why. (T18)
7. **Tenant isolation:** every table has `user_id`, PostgreSQL Row-Level Security is on, and each service has its own DB role with only the tables it needs. (T13)
8. **No secrets in the repo, ever.** The repo is public. `.env` files are git-ignored, secret scanning runs pre-commit and in CI. Never print tokens or keys in logs. (T17, T22)
9. **Settings change only from the verified owner** (direct WhatsApp command from the verified number, or the web app) — never from inbound content. (T4, T29)
10. **Emails the agent sends include a disclosure line** stating they were sent by the user's agent.
11. **Unusual requests need extra verification** (secret question / PIN), defined by fixed rules for now: new recipient, cancelling more than two meetings, changing sensitive settings. (T8, T29)
12. **Emergency stop** (secret code from any phone) only pauses the agent and cancels pending actions. Resuming requires web login. The stop check runs before any other processing, with rate limiting. (T11, T28)

## Architecture at a glance

| Service | Role | Stack |
|---|---|---|
| `api` | Web app API, WhatsApp webhooks (signature-verified), Google login, approvals | Python, FastAPI |
| `google-gateway` | The only holder of Google tokens; email polling + rule-based filter, free/busy, policy guard, execution | Python |
| `agent` | Understands requests, returns a structured action plan (JSON validated against a schema). No tokens; network access only to Redis and the LLM provider | Python, LangGraph |
| `web` | Approval queue, history, summaries, contacts, settings | React, TypeScript, Vite |

Data: PostgreSQL (with RLS) and Redis Streams (queues, locks, rate limits). Scheduled jobs run as Kubernetes CronJobs later; Docker Compose locally first.

Suggested repo layout (confirm in the Layer 0 plan):

```
services/api/
services/google_gateway/
services/agent/
packages/shared/        # shared schemas (Pydantic) and utilities
web/
deploy/compose/         # Docker Compose for local dev
deploy/helm/            # later (Layer 2)
infra/terraform/        # later (Layer 6)
evals/                  # agent evals (synthetic Hebrew/English emails)
redteam/                # attack corpus from the threat model
docs/                   # design docs (Hebrew)
docs/adr/               # architecture decision records
```

## Build order

Work strictly in the layers defined in `docs/03-architecture.md`. Do not jump ahead.

- **Layer 0 — skeleton:** repo structure, Docker Compose (Postgres, Redis), empty FastAPI service, `.gitignore`, pre-commit (ruff, gitleaks), basic GitHub Actions CI. *(current)*
- **Layer 1 — MVP core:** end-to-end thin path on a demo Gmail account: email → detection → slots → draft → approval → send + Meet event.
- **Layers 2–6:** Kubernetes + GitOps, observability, evals + red team in CI, detection layer, temporary cloud.

## Conventions

- Python 3.12+. ruff for lint/format, mypy (strict where practical), pytest. Pydantic models for every schema that crosses a boundary.
- TypeScript in strict mode. API client types generated from FastAPI's OpenAPI.
- Code, comments, commit messages and ADRs in English. The owner prefers to chat in Hebrew.
- Small branches and pull requests. One focused change per PR.
- Every feature has tests. Security-relevant tests are named after the threat they cover, e.g. `test_t5_new_recipient_requires_explicit_approval`.
- Record significant decisions as `docs/adr/NNN-short-title.md` (context, decision, alternatives, consequences).
- Ask before adding a new dependency, service, or anything that costs money.

## Working with the owner

- Plan before coding anything non-trivial, and wait for approval of the plan.
- Explain the "why" behind design choices in plain terms. The owner wants to fully understand the code for interviews.
- Use only the demo Google account and synthetic data. Never put real emails, names or numbers in fixtures, tests or commits.
- Budget is about $30/month on top of the Claude Code subscription. Prefer free and open-source tools; flag anything with a running cost.

## Decided (do not reopen without asking)

Python; LangGraph (ADR-002 alternatives: Claude Agent SDK, OpenAI Agents SDK); polling Gmail every minute in the MVP; Redis Streams; PostgreSQL RLS; four services split by key ownership; React; Sealed Secrets; temporary cloud = k3s on one AWS server via Terraform; WhatsApp via Meta Cloud API directly with a dedicated prepaid number; Google OAuth app stays in testing mode for now; rule-based email filtering; Hebrew-only UI for the MVP; demo mode with a demo Google account and fake data.

Still open: whether to add a separate "reader" LLM in addition to key separation (to discuss with the security mentor); which LLM provider/model per task (decide at the start of Layer 1).
