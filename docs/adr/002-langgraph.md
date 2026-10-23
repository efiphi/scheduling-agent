# ADR-002: LangGraph for the agent

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The agent reads untrusted content (emails, forwarded messages), extracts participants, duration and time range, asks for free/busy, and returns a structured action plan. Nothing it produces is executed directly: every plan stops for the policy guard and for a human approval. The framework must make that flow visible and auditable, support pausing for a human, persist state between steps, and let us swap LLM providers per task (the provider choice is still open until Layer 1).

## Decision

Build the agent with LangGraph: an explicit state graph where each node is one step (extract, request availability, plan), with typed state, checkpoints stored in Redis (the agent has no database access, see ADR-011), and the plan validated against a JSON schema before it leaves the service.

## Alternatives considered

- **Claude Agent SDK** — an excellent agent loop, but it is built around an autonomous model that decides which tools to call. Here we want the opposite: a fixed, inspectable flow where the model fills in fields and never chooses actions. It also ties the agent to one provider.
- **OpenAI Agents SDK** — the same autonomy-first design and the same provider lock-in.
- **Plain API calls without a framework** — the most transparent option, but we would hand-build state, checkpoints, retries and tracing hooks.

## Consequences

- **Positive:** The control flow is code, not model behavior, so a manipulated model cannot add steps (T1–T7). Human-in-the-loop interrupts and checkpoints are built in. The graph is easy to draw and explain in an interview. Provider-agnostic, so the per-task model choice stays open.
- **Negative:** A framework with its own abstractions and a fast-moving API; versions must be pinned (T20). Some LangChain concepts leak in and need to be understood.

## Revisit when

The graph turns out to be a straight line with no branching or interrupts — then plain API calls are simpler — or LangGraph's API churn costs more time than it saves.

## References

- `docs/03-architecture.md` — main flows, ADR list
- `docs/02-threat-model.md` — T1–T7, principle 2 (decisions in code, not the model)
