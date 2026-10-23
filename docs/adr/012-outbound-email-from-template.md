# ADR-012: Outbound email is built from a template in `google-gateway`

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Every email the agent sends on the user's behalf must contain only scheduling content (T1, E5), must never explain availability with details of other meetings (E6), and must include a disclosure line saying it was sent by the user's agent (invariant 10). If the model writes the whole email, all of that depends on the model behaving, and the policy guard would have to inspect free text to catch a leak.

## Decision

The agent's plan contains structured fields — recipients, the chosen slots as timestamps with time zones, the language, and a short free-text opening line (length-limited). `google-gateway` builds the email from a fixed template per language:

- Slots are formatted by code, with the time zone stated explicitly (E3).
- The disclosure line is added by code, always.
- The model's opening line is the only free text. The policy guard checks it for length, links, email addresses, phone numbers and any non-scheduling content, and the preview highlights it (E5, T12).

## Alternatives considered

- **Model writes the full email; the guard inspects it** — the most natural-sounding replies, but detecting leaks and commitments in free text is itself a fuzzy, model-like problem, and the disclosure line could be dropped.
- **Template only, no model text** — the safest option, but replies sound robotic, especially in Hebrew, which hurts the user's reputation (an asset in the threat model).

## Consequences

- **Positive:** The disclosure line and the slot details cannot be removed or altered by a manipulated model. What leaves the system is mostly code-generated and easy to test. The guard only has to check one short sentence.
- **Negative:** Replies are less flexible; unusual threads (several participants, a counter-proposal with conditions) may need template variants. Templates must be maintained in Hebrew and English.

## Revisit when

Users regularly edit the drafts because the template does not fit, which would show up in the history as edits before approval.

## References

- `docs/03-architecture.md` — main flows (incoming email, steps 4–6)
- `docs/02-threat-model.md` — T1, T12, T30, E3, E5, E6
