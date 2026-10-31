# ADR-017: The WhatsApp channel — signed webhook, inbound verification, one template

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

WhatsApp is the fast channel between a user and their agent (docs/01-use-cases.md, UC-W*). The webhook URL is public, and anyone who knows the agent's number can message it. The channel must:
- accept only Meta's calls;
- act only for the verified owner;
- let a backup phone stop the agent (ADR-014).

Meta's rules shape the design. A business may write freely only within **24 hours of the user's last message**. Outside that window it may send only **pre-approved templates**, and those are paid.

## Decision

- **The api holds the Meta token, alone.** It is a System User token with only `whatsapp_business_messaging` and `whatsapp_business_management`, and it never expires (T18).
- **Every webhook call is checked against Meta's signature** (`X-Hub-Signature-256`, an HMAC-SHA256 of the raw body with the App Secret), in constant time, before the body is read (T8). The one-time URL handshake checks our own verify token.
- **The order per message:**
  1. a rate limit per sender;
  2. the sender is identified by number only, through `app.whatsapp_senders` (a hardened SECURITY DEFINER function, migration 0005);
  3. **the stop code first** (invariant 12);
  4. then the owner's message.

  An unknown number is dropped with no reply and only a security event. The number itself is not stored (UC-W7). A backup number can only stop.
- **The stop code** is an argon2id hash, checked only against the users this number belongs to. Five wrong codes from one number lock its stop attempts for an hour (T28).
- **Inbound verification.** The web app shows a one-time 8-character code (10 minutes, single-use, stored as a hash). The user sends it from their phone to the agent. That proves the number is theirs and opens the 24-hour window. No template, no SMS (invariant 11 rules out SMS anyway).
- **Notifications** use free-form messages with buttons inside the window. Outside it, one approved utility template tells the user that an action is waiting (step 1b-2).
- **Development exposure:** a Cloudflare *quick* tunnel. It needs no account and no domain, and its URL changes on every run, so Meta's webhook setting is updated each time. A fixed URL comes with the cloud server (Layer 6).

**Implementation of approvals (step 1b-2):**
- google-gateway announces a new pending action on `api:notifications`, by id only.
- The api's `notifier` reads the action from the database itself.
- **Inside the window,** it sends the action with Approve / Reject reply buttons. The approve button's id carries the action id **and its content hash**, so pressing it approves exactly the content in that message (invariant 4). It goes through the same single-use approval record as the web app, with channel `whatsapp`.
- **Outside the window,** it sends the template named in `WHATSAPP_NOTIFY_TEMPLATE`, if one is approved. Any reply from the owner opens the window and brings every waiting action with buttons.
- A button the api did not create is a security event and is never guessed at.

## Alternatives considered

- **Outbound verification code (the agent sends it).** This was the original plan in docs/04-web-app.md. It needs a template for the very first message, so it would have been paid and needed approval before anything works.
- **SMS verification.** Excluded by invariant 11 (SIM swapping).
- **A named Cloudflare tunnel.** It gives a stable URL, but it needs a domain on Cloudflare (about $10 a year). Not worth it before the cloud layer.
- **A WhatsApp SDK.** The API surface we use is three HTTPS calls; `httpx2` is already a dependency.

## Consequences

- **Positive:** a forged webhook does nothing, and an unknown number learns nothing. A stolen phone can be stopped from a backup phone without the stolen phone's code being guessable. Verification costs nothing.
- **Negative:** messages outside the window cost money (a utility template; check Meta's Israel price before production use). The quick-tunnel URL must be re-registered with Meta after every restart. The test number can message at most five verified recipients.

## Revisit when

The system runs in the cloud (fixed URL), or more than a handful of users join (the template cost and the test number's limits).

## References

- ADR-006, ADR-014
- `docs/02-threat-model.md`: T8, T11, T18, T28
- `services/api/src/api/whatsapp.py`, `packages/db/migrations/versions/0005_whatsapp_numbers.py`
