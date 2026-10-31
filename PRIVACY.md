# Privacy policy — Scheduling Agent

*Last updated: 31 October 2026*

Scheduling Agent is a personal, open-source portfolio project. It helps its invited users
schedule meetings from their own Gmail, Google Calendar and WhatsApp. It is not a commercial
service, and it is used only by people its owner invited. The source code is public:
<https://github.com/efiphi/scheduling-agent>.

## What it processes, and why

| Data | Why | Kept |
|---|---|---|
| Your Google account email | to log you in (identity only) | while your account exists |
| A Google refresh token for Gmail and Calendar | to read new email, check free/busy times, send replies and create events **you approve** | encrypted (AES-256-GCM), until you disconnect |
| Emails that look like meeting requests | to understand the request; the text is sent to the LLM provider (Anthropic) for this only | the thread's participants and state; not the body |
| Sender, subject and time of emails it skipped | so you can see what it ignored | 7 days |
| Your calendar's busy times | to propose free slots; titles, descriptions and attendees are never read | not stored |
| Your WhatsApp number and up to two backup numbers | so the agent talks only to you, and so a backup phone can stop it | while your account exists |
| WhatsApp messages you send the agent | to act on them (approvals, the stop code) | not stored; an audit record of the action only |
| An audit log of actions and approvals | security and accountability | anonymised when your account is deleted |

## What it never does

- It never sends an email, creates an event or replies on WhatsApp to anyone other than you
  without your explicit approval of that exact content.
- It never reads email bodies of messages it skipped beyond deciding whether they are a
  meeting request, and never stores them.
- It never sells, shares or uses your data for advertising or for training models.
- It cannot delete your email: the Gmail permission it asks for does not allow it.

## Third parties

- **Google** (Gmail, Calendar, login), under your Google consent.
- **Anthropic** (the language model): only the text of emails that passed the meeting-request
  filter. Anthropic's commercial API does not train on this data by default and deletes it
  within 30 days.
- **Meta** (WhatsApp Cloud API): messages between you and the agent.

## Your choices

- Disconnect Google at any time from the web app or from your Google account
  (myaccount.google.com/permissions).
- Pause the agent from the web app, or with your stop code from your phone or a backup phone.
- Ask for your account and data to be deleted: open an issue on the GitHub repository above,
  or ask the owner who invited you. Deletion removes all data and tokens; only anonymised
  audit records remain.

## Security

Tokens are encrypted; each service has only the access it needs; the database isolates users
from each other; every outgoing action passes fixed checks in code and needs your approval.
The full threat model is in `docs/02-threat-model.md`.
