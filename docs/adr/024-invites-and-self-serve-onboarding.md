# ADR-024: Joining by invite link, and connecting Google from the web app

## Status

Accepted (24 November 2026)

## Context

Until now a new user was created by the owner with a database command, and Gmail and Calendar were connected by running another command inside the gateway pod. Only the owner could do either, so nobody else could try the agent. In the cloud the gateway's own "connected" page was not even routed, so the browser ended on the web app's 404.

The design always said joining is by a single-use, expiring invite bound to one address (T14), with Google connected from the web app (UC-A1). Two invariants shape how: the api never sees a Google token (invariant 1), and every table has Row-Level Security (invariant 7).

## Decision

**Invites live in Postgres, and Postgres enforces the rules.** Migration 0007 adds `app.invites`, which has RLS like every table:

- **What is stored:** the SHA-256 of the link's token, never the token, so a dump of the database holds no usable link.
- **Who may invite:** an insert needs the inviter to be an admin, checked by the policy itself. A bug in the api cannot let an ordinary user invite anyone.
- **Who marks an invite used:** only `app.accept_invite`. It locks the invite row, checks that it is live and bound to this verified address, and creates the user, their settings and the audit row in the same transaction. When two logins race with one link, the second waits on the lock and then finds the invite used.
- **Who may grant admin:** nobody through a service. No service role may change `users.is_admin`; only the owner can.

**The token never reaches a log.** The link is `…/invite#<token>`. Browsers never send what follows `#` to a server, so the token cannot reach Traefik's or nginx's logs, a Referer header, or a trace. The web app reads the token from the fragment, removes it from the address bar, and posts it in a JSON body.

- **Lifetime:** 72 hours, once, for one address.
- **What an unknown link sees:** one 404, whatever the reason, and only a hint of the address, such as `d***@example.com`.
- **Which login can join:** only a login that started from an invite can accept one. A login with a different account is refused, and the invite stays usable for the right account.

**Connecting Google goes through a one-time ticket.** The gateway has no sessions, and the api must not run the consent. So:

1. The logged-in user asks the api, with a session and a CSRF token.
2. The api puts a ticket in Redis: 256 random bits, stored by hash, holding the user id and the screen to return to, for 5 minutes.
3. The browser takes the ticket to `/oauth/google/start` on the gateway. The gateway redeems it once (GETDEL) and starts the consent for that user.
4. After Google's callback, the gateway sends the browser back to the web app with an outcome code only.

The screens it can return to are a fixed list, so this is not an open redirect. An invalid ticket is counted as a metric and not stored, so it cannot be used to fill the database.

**The api learns only the connection's status.** Migration 0008's `app.google_status()` returns one word for the current user (connected, expired, revoked or not_connected). The api still has no grant on `google_credentials`.

## Alternatives

- **Token in the path (`/invite/<token>`), as first sketched.** Simpler, but the token would sit in every proxy log and trace. Rejected.
- **Checking invites in the api only.** Rejected: one missed check would let anyone invite. A database policy holds even when the code is wrong.
- **Email the invite from the system.** The api has no Gmail access by design, and the gateway sends only scheduling replies from the user's own mailbox. The admin copies the link and sends it however they like.
- **The api starts the Google consent and hands the code to the gateway.** Rejected: the code is exchangeable for tokens, and the api would hold it (invariant 1).
- **Publishing the Google OAuth app.** This would remove the 100-test-user limit, but restricted Gmail scopes require Google's security assessment, which costs thousands of dollars. The app stays in testing mode.

## Consequences

- An admin invites from `/admin/users`, and the invitee joins, connects Google, verifies WhatsApp and sets a stop code without the owner touching a terminal.
- **Two manual steps remain**, and the admin screen shows them with every new link:
  - The invitee's address must be added as a test user on the Google OAuth consent screen (testing mode).
  - Their WhatsApp number must be added as a recipient of Meta's test number, which can message at most five numbers.
- In testing mode a Google connection still expires after 7 days. The web app now shows this and offers a reconnect button instead of a dead one.
- Removing a user is not part of this decision. It comes with account deletion (UC-A7).
- The working-hours and PIN steps of onboarding wait for their APIs. Defaults apply until then.
