# ADR-007: React, TypeScript and Vite for the web app

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The web app is the full control surface: approval queue, history, summaries, contacts, settings and security. It must update in real time (Server-Sent Events) so an action approved on WhatsApp disappears from the queue, render Hebrew right-to-left, and show email-derived content only as text (T19). It is mostly used on a phone.

## Decision

A single-page app with React, TypeScript in strict mode and Vite. The API client and its types are generated from FastAPI's OpenAPI schema, server data is managed with TanStack Query, styling uses Tailwind with logical properties for RTL, and the build output is served as static files from an nginx container with security headers (CSP, frame-ancestors).

## Alternatives considered

- **Server-rendered templates with HTMX** — less JavaScript and no separate build, a reasonable fit for a small app. Rejected because frontend basics in React and TypeScript are one of the job-market gaps this project is meant to close, and generated types from OpenAPI keep the client in sync with the API.
- **Next.js** — server rendering is unnecessary for a logged-in app and would add a Node server to run and secure.

## Consequences

- **Positive:** The most requested frontend stack. React escapes text by default, which supports the "external content is always text" rule (T19); any use of `dangerouslySetInnerHTML` is forbidden and easy to lint for. Generated types catch API drift at build time.
- **Negative:** A separate Node toolchain and its npm dependencies (T20), so lockfiles and dependency scanning apply here too. More code than HTMX for the same screens.

## Revisit when

The app stays a handful of simple screens and the frontend tooling costs more time than it teaches.

## References

- `docs/04-web-app.md` — principles, implementation notes
- `docs/02-threat-model.md` — T19, T20
