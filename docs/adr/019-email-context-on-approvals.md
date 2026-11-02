# ADR-019: Show the incoming email's context next to an approval

## Status

Accepted (2 November 2026)

## Context

The approval card showed the reply and its recipients, but not what it answers: no subject and no content. Meeting requests often sit inside a longer email. A user could approve a reply without knowing what the email was about, or that it also asked for something the reply ignores.

A summary needs a model that reads the email, and the email is written by an outsider. So the summary is text an attacker can influence, placed right where the user decides (T31).

## Decision

Every pending action created from an email carries, in its payload, an `incoming` block:

- **Sender:** the parsed address, not the display name, which anyone can set freely.
- **Subject:** with line breaks and invisible or direction-changing characters removed.
- **Summary:** in Hebrew, written by the model in the existing extraction call, so there is no second call. It covers what the sender wants and every other topic in the email.

Rules that keep the summary harmless:

- **Display only.** No code reads it to decide anything. Recipients, slots and the outgoing email do not depend on it, and it never reaches the outgoing email.
- **Checked twice, in code.** The agent checks it, and so does the gateway, since the agent reads attacker-written email. See `shared/display.py`.
- **Never cut.** A summary may be as long as the email needs, up to 1,500 characters. Half a sentence can change the meaning, so one that breaks a rule is dropped whole, and the card says to read the original.
- **No links, addresses or long numbers.** A summary with one is dropped, so that it cannot place a phishing link in front of the user.
- **Labelled.** The card says it was written from external content and is not verified.
- **Covered by the content hash,** since `incoming` is part of the payload. An approval binds to what the user saw.

On WhatsApp, a message with buttons holds at most 1,024 characters, and the old code cut anything longer without saying so. Now a longer card goes out as ordinary messages, followed by the buttons with a short question. The buttons carry the action's hash as before.

## Alternatives

- **A verbatim excerpt from the start of the email.** The model cannot distort it, but in a long email it can miss the point, which is the case this is for.
- **A link to the email in Gmail.** Built and tried, then removed at the owner's request: it added little on a phone, and the card already says what the email is about.
- **Sender and subject only.** No new risk, but the subject says little when the request is part of a longer email.
- **A separate model call for the summary.** Costs more, and the same content reaches a model either way.
- **A hard limit of two sentences.** Rejected by the owner: it can cut the content short, and the point is to know what the email says.

## Consequences

- **Positive:** the user can decide from the card, and sees when an email asks for more than a meeting.
- **Negative:** a manipulated summary can still mislead. The damage is limited to the user approving a reply with slots, which passes the policy guard as usual, and the original stays in the user's mailbox.
- **Negative:** text derived from third-party email is now stored in `pending_actions` and passes through Meta, as the outgoing reply already does. Logs and traces stay free of it (T22).
- **Negative:** about 350-450 more output tokens per email, measured on two test emails (272 before, 613 and 721 after), which at Haiku prices is about $0.0002 per email. `MAX_TOKENS` goes from 1024 to 2048 so that a long summary does not truncate the form.
- **Not covered yet:** questions to the user (UC-M7) still show no email context.
- **To check:** red-team cases for T31 go into Layer 4.
