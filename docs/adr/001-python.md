# ADR-001: Python 3.12+ for all backend services

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Three backend services (`api`, `google-gateway`, `agent`) need a language. The agent depends on an LLM orchestration framework, the gateway on Google's client libraries, and the API on a web framework that can generate an OpenAPI schema for the frontend. The owner works roughly 2–9 hours a week and must be able to explain every line in interviews, so one language across the backend matters more than squeezing out performance.

## Decision

Use Python 3.12+ for every backend service, with ruff (lint and format), mypy (strict where practical), pytest, and Pydantic models for every schema that crosses a service boundary.

## Alternatives considered

- **TypeScript / Node.js** — one language with the frontend, but the agent ecosystem (LangGraph, evals tooling) is most mature in Python, and the owner's prior work is in Python.
- **Go** — strong fit for small, fast services, but weak LLM tooling and a new language to learn alongside everything else.

## Consequences

- **Positive:** The language that appears most in AI Engineer, security tooling and platform job postings. Shared Pydantic schemas in `packages/shared` give one source of truth for message formats between services. FastAPI produces the OpenAPI schema that the web client is generated from.
- **Negative:** Dynamic typing needs discipline; mypy and Pydantic carry that load. Slower than Go, which does not matter at this scale (one to a few users, polling once a minute).

## Revisit when

A service becomes CPU-bound in a way that matters to users, or a required SDK exists only in another language.

## References

- `docs/03-architecture.md` — ADR list, components table
