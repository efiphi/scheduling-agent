# ADR-015: Claude Haiku 5.5 for the agent, verified on synthetic emails first

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

The agent does two narrow jobs: extract participants, duration and time range from a short email (Hebrew or English) into a fixed schema, and write one short opening line for the reply (ADR-012). Everything else — slot selection, the email body, the disclosure line, every check — is code.

Constraints:
- **Output must fit a schema exactly.** The plan is validated by `StrictModel`; an unknown field rejects the whole message (T1–T7).
- **Hebrew and English**, including Hebrew date expressions ("יום שלישי הבא", "אחרי החג") (E4).
- **Budget** about $30/month for everything; the LLM estimate in the architecture doc is $5–15.
- **Provider exposure** (T23): every email that passes the rule-based filter is sent to the provider.

Volume is low: at most a few dozen filtered emails a day, each a few hundred to a couple of thousand tokens.

## Decision

Use **Claude Haiku 5.5** (`claude-haiku-5-5`) through the official `anthropic` Python SDK, with **structured outputs** so the API itself constrains the response to the plan's JSON schema, and `effort: "low"` for extraction.

Before relying on it, measure it: 10–15 synthetic emails (Hebrew and English, including ambiguous dates and an injection attempt) with expected extractions. If Haiku 5.5 misses on Hebrew dates or participants, switch to **Claude Sonnet 5.5** — a one-line model change, recorded as an update to this ADR. This small set is the seed of the Layer 4 eval suite.

Handling rules:
- A `refusal` stop reason, a schema failure, or low confidence is treated as an **unclear request** (UC-M7): the user is asked, nothing is guessed.
- The model is called only from the `agent` service, which holds no Google tokens and no database access (ADR-006, ADR-011); the LLM API key is the only secret it holds.
- Spend is capped twice: a monthly limit in the Anthropic console, and the daily cost counter in code that pauses processing (T24).

**Data handling** (Anthropic's published policy, checked on 2026-10-26): inputs and outputs of the commercial API are **not used for model training** by default (exceptions: feedback submissions, or an explicit opt-in — neither is used here), and are **deleted within 30 days**, except content flagged under the Usage Policy (up to 2 years). Only filtered emails are sent, with only what extraction needs; calendar details never are (invariant 5). Development uses only the demo account and synthetic data.

## Alternatives considered

- **Claude Sonnet 5.5** — stronger, roughly $8/month at our volume, most of the fixed budget. Kept as the fallback if measurement shows Haiku is not enough.
- **Claude Opus 5.5** — about twice Sonnet's price; nothing in these two narrow tasks needs it.
- **A local model via Ollama** — free, and email never leaves the machine (strongest answer to T23). Rejected for now: weaker Hebrew, no API-enforced structured output, and it would not run on the temporary single-server cloud environment (ADR-009). Worth revisiting for the "reader" model question.
- **OpenAI or Google models** — comparable options. Not chosen: the LangGraph design (ADR-002) keeps the provider swappable, and one provider keeps setup, keys and billing simple.

## Consequences

- **Positive:** Expected LLM cost well under $1/month at current volume. Schema conformance enforced by the API, then again by `StrictModel`. The choice rests on a measurement, not on a guess.
- **Negative:** One provider sees the filtered email content (T23), mitigated by filtering, minimal content and the retention policy above. Haiku has no server-side refusal fallback, so refusals are handled in our code. A new paid account and an API key to protect (T17).

## Revisit when

The synthetic set shows Haiku misreading Hebrew requests; volume or users grow enough that cost or rate limits matter; or the open "reader model" question (to discuss with the security mentor) is decided.

## References

- `docs/03-architecture.md` — components (Agent), estimated costs, open questions
- `docs/02-threat-model.md` — T1–T7, T23, T24, E3, E4
- ADR-002, ADR-006, ADR-011, ADR-012
- Anthropic privacy articles: "Is my data used for model training?" and "How long do you store my organization's data?" (privacy.claude.com)
